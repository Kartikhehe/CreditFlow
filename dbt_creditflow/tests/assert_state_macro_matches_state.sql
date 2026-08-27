-- The state unemployment attached to a loan must be the series for that loan's
-- own state. A join that dropped the state predicate would still populate the
-- column, so the check compares against an independent lookup.
with expected as (

    select
        loans.loan_id,
        state_level.unemployment_state as expected_state_unemployment
    from {{ ref('stg_loans') }} as loans
    left join {{ ref('stg_macro_state') }} as state_level
        on state_level.month = loans.issue_month
       and state_level.state_code = loans.state_code

)

select
    fct.loan_id,
    fct.geography_key,
    fct.state_unemployment_at_origination,
    expected.expected_state_unemployment
from {{ ref('fct_loan') }} as fct
join expected
    on expected.loan_id = fct.loan_id
where fct.state_unemployment_at_origination
      is distinct from expected.expected_state_unemployment
