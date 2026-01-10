# Plugins documentation

This folder explains how to build, test, and ship plugins for the bot.
If you only want a minimal working example, start with quickstart.

## What you will learn

- How plugins are discovered and loaded
- The plugin lifecycle and hook order
- The status rendering pipeline and status API
- Permission requests and user approvals
- Sandbox and filesystem limitations
- How to expose metadata (name, author, repo)

## Plugin API version

The current plugin API version is 2.0.0. Each plugin should declare the
API version it targets so the core can warn about incompatibilities.

## Recommended reading order

1) introduction.md
2) quickstart.md
3) lifecycle.md
4) status_api.md
5) permissions.md
6) sandbox.md
7) filesystem_rules.md
8) debugging.md
9) authoring.md
10) faq.md
