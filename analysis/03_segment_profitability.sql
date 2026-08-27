-- Realised return by FICO band and grade, ranked within band. Uses net cash
-- flow rather than the default rate as the ordering: a segment can default
-- often and still earn, if the coupon it was priced at covers the loss.
select
    borrower.fico_band,
    fct.grade,
    count(*)                                                        as loans,
    round(avg(fct.interest_rate), 2)                                as avg_rate,
    round(100.0 * avg(cast(fct.is_default as double)), 2)           as default_rate_pct,
    round(sum(fct.funded_amount) / 1e6, 1)                          as funded_musd,
    round(sum(fct.net_cash_flow) / 1e6, 2)                          as net_profit_musd,
    round(100.0 * sum(fct.net_cash_flow) / sum(fct.funded_amount), 2) as return_on_funded_pct,
    round(100.0 * sum(fct.realised_loss) / sum(fct.funded_amount), 2) as loss_rate_pct,
    rank() over (
        partition by borrower.fico_band
        order by sum(fct.net_cash_flow) / sum(fct.funded_amount) desc
    )                                                               as return_rank_in_band
from marts.fct_loan as fct
join marts.dim_borrower as borrower
    on borrower.borrower_key = fct.borrower_key
where fct.is_terminal
group by
    borrower.fico_band,
    fct.grade
having count(*) >= 500
order by
    borrower.fico_band,
    return_rank_in_band
