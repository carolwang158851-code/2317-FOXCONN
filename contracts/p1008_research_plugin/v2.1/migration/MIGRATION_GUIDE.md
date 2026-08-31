# v2.1 Candidate Migration Guide

1. Load and verify immutable v1.0 authority.
2. Preserve the accepted v2.0 additive governance overlay.
3. Verify the v2.1 candidate manifest and both normative dependencies.
4. Apply `policies/plugin_policy.json` as an additive filesystem-policy
   overlay; do not replace the v1.0 policy file.
5. Keep Production promotion disabled until Owner acceptance binds the final
   v2.1 manifest and root hash.

Rollback removes the v2.1 selection from the development implementation and
returns to accepted v1.0 plus v2.0 authority. No historical contract file or
acceptance record is rewritten during either migration or rollback.
