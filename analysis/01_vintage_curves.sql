-- Cumulative default rate by months on book, per origination vintage.
-- Reading down a column compares cohorts at equal maturity, which is the only
-- fair comparison when recent vintages have had less time to season.
with base as (

    select
        vintage_quarter,
        months_on_book,
        is_default,
        funded_amount
    from marts.fct_loan
    where is_terminal
      and months_on_book between 0 and 60

),

vintage_size as (

    select
        vintage_quarter,
        count(*)            as cohort_loans,
        sum(funded_amount)  as cohort_balance
    from base
    group by vintage_quarter

),

defaults_by_mob as (

    select
        vintage_quarter,
        months_on_book,
        sum(case when is_default = 1 then 1 else 0 end)              as defaults,
        sum(case when is_default = 1 then funded_amount else 0 end)  as default_balance
    from base
    group by
        vintage_quarter,
        months_on_book

),

cumulative as (

    select
        defaults_by_mob.vintage_quarter,
        defaults_by_mob.months_on_book,
        sum(defaults_by_mob.defaults) over (
            partition by defaults_by_mob.vintage_quarter
            order by defaults_by_mob.months_on_book
            rows between unbounded preceding and current row
        )                                   as cumulative_defaults,
        sum(defaults_by_mob.default_balance) over (
            partition by defaults_by_mob.vintage_quarter
            order by defaults_by_mob.months_on_book
            rows between unbounded preceding and current row
        )                                   as cumulative_default_balance,
        vintage_size.cohort_loans,
        vintage_size.cohort_balance
    from defaults_by_mob
    join vintage_size
        on vintage_size.vintage_quarter = defaults_by_mob.vintage_quarter

)

select
    vintage_quarter,
    months_on_book,
    cohort_loans,
    round(100.0 * cumulative_defaults / cohort_loans, 3)                 as cumulative_default_rate_pct,
    round(100.0 * cumulative_default_balance / cohort_balance, 3)        as cumulative_default_rate_balance_pct
from cumulative
where cohort_loans >= 500
order by
    vintage_quarter,
    months_on_book
