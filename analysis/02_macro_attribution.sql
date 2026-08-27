-- Splits quarter-on-quarter movement in the default rate into a risk-mix
-- component and a macro component. The attribution is directional, not a
-- decomposition: it flags which explanation is consistent with the observed
-- deltas so the follow-up question is narrower.
with vintage_stats as (

    select
        fct.vintage_quarter,
        fct.issue_year,
        count(*)                                        as loans,
        avg(cast(fct.is_default as double))             as default_rate,
        avg(borrower.fico_score)                        as avg_fico,
        avg(borrower.debt_to_income)                    as avg_dti,
        avg(fct.interest_rate)                          as avg_rate,
        avg(fct.state_unemployment_at_origination)      as avg_state_unemployment,
        cast(sum(case when fct.grade in ('D', 'E', 'F', 'G') then 1 else 0 end) as double)
            / count(*)                                  as pct_high_risk_grade
    from marts.fct_loan as fct
    join marts.dim_borrower as borrower
        on borrower.borrower_key = fct.borrower_key
    where fct.is_terminal
    group by
        fct.vintage_quarter,
        fct.issue_year

),

with_deltas as (

    select
        vintage_stats.*,
        default_rate - lag(default_rate) over (order by vintage_quarter)
            as default_rate_change,
        avg_fico - lag(avg_fico) over (order by vintage_quarter)
            as fico_change,
        pct_high_risk_grade - lag(pct_high_risk_grade) over (order by vintage_quarter)
            as risk_mix_change,
        avg_state_unemployment - lag(avg_state_unemployment) over (order by vintage_quarter)
            as unemployment_change
    from vintage_stats
    where loans >= 1000

)

select
    vintage_quarter,
    loans,
    round(100 * default_rate, 2)            as default_rate_pct,
    round(100 * default_rate_change, 2)     as default_rate_change_pp,
    round(fico_change, 1)                   as fico_change,
    round(100 * risk_mix_change, 2)         as risk_mix_change_pp,
    round(unemployment_change, 2)           as unemployment_change_pp,
    case
        when default_rate_change > 0 and risk_mix_change > 0.02      then 'Underwriting mix shift'
        when default_rate_change > 0 and unemployment_change > 0.3   then 'Macro deterioration'
        when default_rate_change > 0                                 then 'Unexplained, investigate'
        else 'Improving'
    end                                     as attribution_flag
from with_deltas
order by vintage_quarter
