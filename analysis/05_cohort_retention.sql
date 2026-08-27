-- Share of each cohort still performing at a given months-on-book, derived by
-- reverse-accumulating the loans that stopped paying at or before that point.
-- The complement of the vintage curve, read the way a retention table is read.
with cohort as (

    select
        vintage_quarter,
        months_on_book,
        count(*) as loans_exiting_at_mob
    from marts.fct_loan
    where is_terminal
      and months_on_book >= 0
      and months_on_book <= 60
    group by
        vintage_quarter,
        months_on_book

),

cohort_size as (

    select
        vintage_quarter,
        sum(loans_exiting_at_mob) as cohort_loans
    from cohort
    group by vintage_quarter

),

surviving as (

    select
        cohort.vintage_quarter,
        cohort.months_on_book,
        cohort_size.cohort_loans,
        cohort_size.cohort_loans - sum(cohort.loans_exiting_at_mob) over (
            partition by cohort.vintage_quarter
            order by cohort.months_on_book
            rows between unbounded preceding and current row
        ) as loans_still_on_book
    from cohort
    join cohort_size
        on cohort_size.vintage_quarter = cohort.vintage_quarter

)

select
    vintage_quarter,
    months_on_book,
    cohort_loans,
    loans_still_on_book,
    round(100.0 * loans_still_on_book / cohort_loans, 2) as pct_still_on_book
from surviving
where cohort_loans >= 500
order by
    vintage_quarter,
    months_on_book
