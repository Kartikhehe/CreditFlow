{#
    Use the custom schema name verbatim rather than prefixing it with the
    target schema. dbt's default yields main_marts and main_staging, while
    every query in this project, the analysis SQL and the singular tests
    address marts and staging directly.
#}
{% macro generate_schema_name(custom_schema_name, node) -%}
    {%- if custom_schema_name is none -%}
        {{ target.schema }}
    {%- else -%}
        {{ custom_schema_name | trim }}
    {%- endif -%}
{%- endmacro %}
