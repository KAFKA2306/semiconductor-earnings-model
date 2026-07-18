# Semiconductor Earnings Model

Versioned evidence -> deterministic LangGraph calculation -> audit gate -> GitHub Pages.

Public page: https://kafka2306.github.io/semiconductor-earnings-model/

## Update contract

The weekday schedule and changes to main recalculate and republish the model.

1. Add data/quant_audit/semiconductor_YYYYMMDD.json.
2. Recalculate site/public/data/quant-audit.json with the LangGraph runner.
3. Build the /earnings/ route with Astro.
4. Deploy the generated site to GitHub Pages.

Existing snapshots are never overwritten. The JSON keeps source, definition, and open audit findings. Yardeni consensus is secondary information; beta and investment lag are not estimated.

This is not investment advice.
