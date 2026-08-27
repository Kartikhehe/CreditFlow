-- Fails if any loan carries a macro reading that does not belong to its own
-- origination month. Rather than checking the join condition, this recomputes
-- the expected value independently and compares: a regression that widened the
-- join to a nearest-month or forward-filled lookup would still satisfy a
-- condition-shaped test, but it would surface here as a mismatch.
with expected as (

    select
        loans.loan_id,
        national.unemployment_national  as expected_unemployment,
        national.treasury_10y           as expected_treasury_10y,
        national.consumer_sentiment     as expected_sentiment
    from {{ ref('stg_loans') }} as loans
    left join {{ ref('stg_macro') }} as national
        on national.month = loans.issue_month

),

compared as (

    select
        fct.loan_id,
        fct.unemployment_at_origination,
        expected.expected_unemployment,
        fct.treasury_10y_at_origination,
        expected.expected_treasury_10y,
        fct.sentiment_at_origination,
        expected.expected_sentiment
    from {{ ref('fct_loan') }} as fct
    join expected
        on expected.loan_id = fct.loan_id

)

select *
from compared
where unemployment_at_origination is distinct from expected_unemployment
   or treasury_10y_at_origination is distinct from expected_treasury_10y
   or sentiment_at_origination    is distinct from expected_sentiment
