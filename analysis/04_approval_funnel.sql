-- Approval rate and the credit-quality gap between approved and declined
-- applicants, by application year. The gap is the crude measure of how much
-- the existing policy was actually discriminating.
with scored_applications as (

    select
        decision,
        date_trunc('year', application_date) as application_year,
        fico_score
    from marts.fct_application_funnel
    where fico_score between 300 and 900

)

select
    application_year,
    count(*)                                                            as applications,
    sum(case when decision = 'ACCEPTED' then 1 else 0 end)              as approved,
    round(
        100.0 * sum(case when decision = 'ACCEPTED' then 1 else 0 end) / count(*), 2
    )                                                                   as approval_rate_pct,
    round(avg(case when decision = 'ACCEPTED' then fico_score end), 1)  as avg_score_approved,
    round(avg(case when decision = 'REJECTED' then fico_score end), 1)  as avg_score_declined,
    round(
        avg(case when decision = 'ACCEPTED' then fico_score end)
        - avg(case when decision = 'REJECTED' then fico_score end), 1
    )                                                                   as score_gap
from scored_applications
group by application_year
order by application_year
