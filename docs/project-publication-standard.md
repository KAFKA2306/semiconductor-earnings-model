# Project publication standard

This rule applies to all KAFKA2306 projects intended for delivery or public use.

1. The project must publish a usable GitHub Pages endpoint.
2. `README.md` must show the fully qualified GitHub Pages URL near the top under a visible label such as `Live GitHub Pages` or `公開サイト`.
3. A repository-relative path, Actions page, or source-code link does not substitute for the public URL.
4. CI must verify the README link and the deployed endpoint.
5. A change is not complete when code is pushed but the documented public endpoint is missing or fails the live deployment check.

Expected URL convention:

```text
https://<owner>.github.io/<repository>/
```

Reusable checker:

```sh
python scripts/check_readme_pages_link.py --repository "$GITHUB_REPOSITORY"
```
