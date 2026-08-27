-- The funnel is a union of two disjoint populations, so its row count must
-- equal the sum of its parts and no loan may appear on both sides. A silent
-- inner join or a deduplication introduced upstream would drop rows here.
with counted as (

    select
        (select count(*) from {{ ref('fct_application_funnel') }})                      as funnel_rows,
        (select count(*) from {{ ref('fct_application_funnel') }} where decision = 'ACCEPTED') as accepted_rows,
        (select count(*) from {{ ref('fct_application_funnel') }} where decision = 'REJECTED') as rejected_rows,
        (select count(*) from {{ ref('stg_loans') }})                                   as source_accepted,
        (select count(*) from {{ ref('stg_rejected') }})                                as source_rejected

)

select *
from counted
where funnel_rows != accepted_rows + rejected_rows
   or accepted_rows != source_accepted
   or rejected_rows != source_rejected
