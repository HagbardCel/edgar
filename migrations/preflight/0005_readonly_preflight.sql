-- Read-only preflight for Alembic revision 0005_m1a_integrity (run at DB 0004).
-- Each query must return zero rows before upgrade.

-- Duplicate context ids within a report
SELECT report_id, id AS context_id, COUNT(*) AS duplicate_count
FROM source.context
GROUP BY report_id, id
HAVING COUNT(*) > 1;

-- Duplicate unit ids within a report
SELECT report_id, id AS unit_id, COUNT(*) AS duplicate_count
FROM source.unit
GROUP BY report_id, id
HAVING COUNT(*) > 1;

-- Facts referencing missing context rows (same-report)
SELECT f.report_id, f.context_id
FROM source.fact f
LEFT JOIN source.context c ON c.report_id = f.report_id AND c.id = f.context_id
WHERE c.id IS NULL;

-- Facts referencing missing unit rows when unit_id is set
SELECT f.report_id, f.unit_id
FROM source.fact f
LEFT JOIN source.unit u ON u.report_id = f.report_id AND u.id = f.unit_id
WHERE f.unit_id IS NOT NULL AND u.id IS NULL;

-- Facts referencing missing concept_declaration (same-report)
SELECT f.report_id, f.concept_id
FROM source.fact f
LEFT JOIN source.concept_declaration cd
  ON cd.report_id = f.report_id AND cd.concept_id = f.concept_id
WHERE cd.concept_id IS NULL;

-- Labels referencing missing concept_declaration (same-report)
SELECT cl.report_id, cl.concept_id
FROM source.concept_label cl
LEFT JOIN source.concept_declaration cd
  ON cd.report_id = cl.report_id AND cd.concept_id = cl.concept_id
WHERE cd.concept_id IS NULL;

-- References referencing missing concept_declaration (same-report)
SELECT cr.report_id, cr.concept_id
FROM source.concept_reference cr
LEFT JOIN source.concept_declaration cd
  ON cd.report_id = cr.report_id AND cd.concept_id = cr.concept_id
WHERE cd.concept_id IS NULL;

-- Relationships with missing source concept_declaration (same-report)
SELECT r.report_id, r.source_concept_id
FROM source.relationship r
LEFT JOIN source.concept_declaration cd
  ON cd.report_id = r.report_id AND cd.concept_id = r.source_concept_id
WHERE cd.concept_id IS NULL;

-- Relationships with missing target concept_declaration (same-report)
SELECT r.report_id, r.target_concept_id
FROM source.relationship r
LEFT JOIN source.concept_declaration cd
  ON cd.report_id = r.report_id AND cd.concept_id = r.target_concept_id
WHERE cd.concept_id IS NULL;
