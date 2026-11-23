# Z-28 environment choice — supervisor options note

Decision proposed: **run the final evaluation from local Docker Compose on a laptop**, with pre-staged images and the committed 660-case mini-cohort. This does not require Azure, private data or hosted AI access.

| Option | Works offline at presentation? | Setup/maintenance | Risk on demo day |
|---|---|---|---|
| **Isolated Docker Compose on laptop** | **Yes after base/runtime images have been downloaded/built and cached.** No runtime external key; template Copilot. | One start command and explicit demo-only reset. Docker Desktop must already be installed. | Laptop resources/Docker startup; mitigate with advance warm-up and Aabia's independent rehearsal. |
| Refreshed Azure VM (Z-20) | No: needs laptop-to-VM network access. | Existing cloud deployment, but credentials/VM and network upkeep. | Internet, permissions and remote service availability. Keep optional as fallback, not main demo. |
| Dev container | Not reliably offline on first boot: extension, image and toolchain may need downloads. | Reproducible developer tools, more setup for a fresh examiner laptop. | IDE/extension behavior and first-run pulls. |

**Scope:** The isolated Compose project uses loopback-bound web/API ports and its own database volume; PostgreSQL is not exposed to the host. Images use version-specific base tags and app tags derived from Git commit identity. A Docker tag is not an immutable content digest; record actual local image IDs for a final evidence trail. Cached images are required for real offline operation. Browser-hosted fonts degrade to local fallback without changing functionality.

**Recommendation for supervisor:** accept local Compose as the primary demo and use Azure only as an optional contingency. Keep the D-22 real-data backup out of the default seed path; it is unnecessary for the required 660-case reproducibility and contains a different dataset.
