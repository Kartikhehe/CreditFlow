-- Every loan flagged terminal must carry a binary label, and every loan still
-- in flight must not. Either direction breaking means the status mapping has
-- drifted away from the flag that gates the modelling population.
select
    loan_id,
    is_terminal,
    is_default
from {{ ref('fct_loan') }}
where (is_terminal = true and is_default is null)
   or (is_terminal = false and is_default is not null)
