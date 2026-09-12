# Synthetic scenario

This is fictional teaching material, not an investigated customer.
The example author adopts bank I01 unchanged: preview 20 supplied rows, no publication or price/inventory writes.
Main workflow confirmation in the manifest belongs only to this fictional scenario. Obtain your own user's confirmation.
Other global tasks to investigate: publishing, price changes, promotion, failed-job recovery. None is assumed implemented.
The fictional prepare_preview(row_ids) interface is idempotent, writes local artifacts only, and returns artifact_id.
Its output rows and complete side-effect journal have NOT been supplied. No target or actual trace is provided.
Policy: the synthetic bank rules, including EUR and the declared margin formula, are adopted for this example only.
