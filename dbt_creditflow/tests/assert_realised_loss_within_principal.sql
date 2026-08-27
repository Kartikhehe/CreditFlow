-- Realised loss is bounded below by zero and above by the amount funded. A
-- value outside that range means the recovery columns were misaligned, which
-- would flow straight into the profit calculation.
select
    loan_id,
    funded_amount,
    realised_loss
from {{ ref('fct_loan') }}
where realised_loss < 0
   or realised_loss > funded_amount
