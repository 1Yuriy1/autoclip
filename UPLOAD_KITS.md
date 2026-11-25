# Video upload kits

Open a completed project's download icon on the home page, or choose **Upload kit** on a clip card.

Each clip has editable title, description, tags, thumbnail headline and frame time. Save updates before downloading the JPEG preview and upload-details text file. MP4 downloads stream directly from the existing export endpoint. The home-page download icon now lists the project's clips instead of showing a placeholder.

Initial copy comes from existing clip metadata and quoted dialogue; it does not claim fresh AI analysis. Thumbnails use actual source footage, bold typography, and the exported video's orientation. Edits persist in `clip_metadata.uploadKit`; generated JPEGs are cached under `data/upload-kits/`. Missing video files produce an actionable error.

Verification: frontend typecheck and production build; three focused upload-kit unit tests; browser open/edit/save/preview checks; HTTP 200 for saved metadata, JPEG attachment and text attachment; HTTP 206 for the MP4 range request. Automated browser download capture stalled, so operating-system download completion was not verified.

The separate Frame Lab recap workflow remains isolated in `shorts-studio-sandbox`. Its GTA 60-second export completed. The configured text provider returned HTTP 401, so that example is explicitly labeled an extractive transcript draft, not an AI-written plot recap.

## AI artwork

Each upload kit now offers **Generate AI thumbnail**, art direction, **Upload artwork**, **Copy AI brief**, and a reversible switch between artwork and the source-frame thumbnail. The generator uses the saved subject/title/headline and transcript as context. Artwork has baked-in text; regenerate after changing the headline. One image is requested per click, with no automatic retry. Previous image files remain stored.

The app uses `AUTOCLIP_IMAGE_API_KEY` or `OPENAI_API_KEY` from the local environment/.env, with `AUTOCLIP_IMAGE_MODEL` defaulting to `gpt-image-2`. Keys never reach the browser. Provider requests are billed to that API account. Implementation follows https://developers.openai.com/api/docs/guides/image-generation .

A GTA raid concept was generated with Codex imagegen and installed on the one-minute raid clip. Its original is preserved at `output/imagegen/gta6-raid-thumbnail-v1.png`. The app preview/download serves a JPEG copy. A read-only model access check returned HTTP 200; the paid in-app generation test was blocked by automatic approval review because it would transmit clip details to OpenAI and incur a generation charge. It was not retried by another route. Ten local tests pass, including mocked provider success/failure, image storage, path validation, and preserved versions. Frontend typecheck/build pass.

AI artwork is now the default for upload kits without an explicitly saved thumbnail choice. Before the first generation, an empty-state button is shown rather than requesting a missing image. Opening a kit, saving text, and refreshing suggestions do not generate images. Only the Generate button submits one image request; repeated clicks are guarded. Existing artwork can be regenerated explicitly, and a saved video-frame choice remains available.
