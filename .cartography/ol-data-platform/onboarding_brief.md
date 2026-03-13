# FDE Onboarding Brief
> Generated: 2026-03-13 12:13 UTC

## The Five Day-One Questions

### 1. What is the primary data ingestion path?

See LLM response (question 1):


### 2. What are the 3–5 most critical output datasets or endpoints?

See LLM response (question 2):


### 3. What is the blast radius if the most critical module fails?

See LLM response (question 3):


### 4. Where is the business logic concentrated vs. distributed?

See LLM response (question 4):


### 5. What has changed most frequently in the last 90 days (high-velocity files)?

See LLM response (question 5):


---

## Quick Reference

### Critical Modules
- `src/ol_dbt/models/staging/mitxonline/stg__mitxonline__openedx__tracking_logs__user_activity` (PageRank: 0.0062)
- `src/ol_dbt/models/staging/mitxresidential/stg__mitxresidential__openedx__tracking_logs__user_activity` (PageRank: 0.0052)
- `src/ol_dbt/models/intermediate/mitxonline/int__mitxonline__users` (PageRank: 0.0052)
- `src/ol_dbt/models/staging/mitxpro/stg__mitxpro__openedx__tracking_logs__user_activity` (PageRank: 0.0050)
- `src/ol_dbt/models/staging/edxorg/stg__edxorg__s3__tracking_logs__user_activity` (PageRank: 0.0047)

### Entry Points (data sources)
- `platforms` — `?`
- `ol_warehouse_raw_data__raw__irx__edxorg__bigquery__email_opt_in` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__assessment_aiclassifier` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__assessment_aiclassifierset` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__assessment_aigradingworkflow` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__assessment_aitrainingworkflow` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__assessment_aitrainingworkflow_training_examples` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__assessment_assessment` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__submissions_submission` — `?`
- `ol_warehouse_raw_data__raw__mitx__openedx__mysql__submissions_studentitem` — `?`

### Final Outputs (data sinks)
- `afact_discussion_engagement`
- `afact_video_engagement`
- `irx__mitx__openedx__bigquery__email_opt_in`
- `irx__mitx__openedx__mysql__assessment_aiclassifier`
- `irx__mitx__openedx__mysql__assessment_aiclassifierset`
- `irx__mitx__openedx__mysql__assessment_aigradingworkflow`
- `irx__mitx__openedx__mysql__assessment_aitrainingworkflow`
- `irx__mitx__openedx__mysql__assessment_aitrainingworkflow_training_examples`
- `irx__mitx__openedx__mysql__assessment_assessment`
- `irx__mitx__openedx__mysql__assessment_assessmentfeedback`
