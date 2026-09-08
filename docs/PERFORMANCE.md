# Xian-MAGE Performance Guide

This document outlines the performance model, concurrency architecture, target latency goals, and benchmarking methods for the Xian-MAGE real-time visual assistant. Because MAGE overlays interactive components directly onto active gaming environments, keeping UI overhead low and processing inputs near-instantly are critical system design parameters.

---

## 1. Concurrency & Threading Model

To ensure a stutter-free 60 FPS overlay experience during gameplay, all heavy tasks (Network I/O, VLM inference, disk access, character dictionary lookups, and audio parsing) are strictly decoupled from the main GUI thread.

```
+------------------------------------------+
|            PyQt6 Main Thread             | <---+ (signals: updates, completed results)
|  - UI Rendering (OSD, ResultBubbles)     |     |
|  - User Event Handling (hotkeys, clicks) |     |
+------------------------------------------+     |
                     |                           |
        (spawns & manages lifecycle)             |
                     v                           |
+------------------------------------------+     |
|         QThread Background Workers        | ----+
|  - InferenceWorker (OCR & Translation)   |
|  - StatusWorker (Lemonade Health Checks)  |
|  - RaidWorker (Voice Loop)               |
+------------------------------------------+
                     |
         (submits async coroutines)
                     v
+------------------------------------------+
|    AsyncEngine Background Thread Loop    |
|  - Port: http://localhost:13305/v1       |
|  - Async HTTP Streaming connection       |
+------------------------------------------+
```

### GUI Thread Protection
* **No Blocking Calls**: Direct network calls or heavy CPU computations (e.g. image filters, dictionary processing) are strictly forbidden in UI components.
* **Qt Signals**: Background worker threads (extending `QThread`) interact with PyQt6 UI widgets exclusively by emitting thread-safe Qt Signals (`pyqtSignal`).

### Background Worker Submissions
* Long-lived background connections and API calls are handled asynchronously by the `AsyncEngine` (running on a dedicated OS thread named `xian-async-engine`).
* Coroutines are submitted to the engine's event loop via:
  ```python
  self.processor.engine.submit(coro)
  ```

---

## 2. Latency Goals & Benchmark Hardware

### Target Latency
* **Target: Instantaneous translation and OSD feedback.**
* To support seamless gaming HUD functionality, visual translations and OCR responses should stream back or populate as close to real-time as the hardware accelerators permit.

### Target Benchmarking Hardware
We target local acceleration of Xian's own virtual multi-model collection `Xian-Ultra` (which routes chat and vision commands to the ~9B parameter `Qwen3.5-9B-GGUF` model); `Xian-Lite` is the ~4B comparison point on constrained hardware. Key benchmark environments include:
1. **AMD Radeon™ RX 7900 XTX** (Vulkan/ROCm acceleration)
2. **Apple Silicon M4** (Metal acceleration)

### Measured: the local OCR live engine

Numbers from `apps/mage-client/test_live_ocr_benchmark.py`, run against the 33-frame
screenshot corpus.  They come out through `record_property`, so a regression shows up as a
changed value rather than only as a failure.

| Measurement | Value | Why it matters |
|---|---|---|
| Region-sized frame, read (detect + rectify + recognize) | **110 ms median**, 344 ms max | The bar was 342 ms — what the retired OCR sidecar cost for the same work. This fits inside a 700 ms tick with room for the paint. |
| Whole corpus, read | 284 ms median, 772 ms max | The maximum is a full 5 MP desktop carrying ~140 lines. Live mode reads a locked region, not a desktop, so it never pays this. |
| Frames yielding no text | **0 of 33** | A frame that reads as empty paints nothing, which looks exactly like the overlay being broken. |
| Identical re-read rate | **1.0** | The property the text gate depends on. A reader that disagrees with itself between identical frames would change the content hash every tick and hold nothing back. |
| Translation calls vs. the pixel gate | 33 vs. 33 | **Not yet demonstrated.** The corpus is 33 distinct stills, so every frame is a genuine change and both gates fire on all of them. The ratio needs a sequence capture of real play. |

If the read lands over budget on a given machine, the levers in order are
`limit_side_len` 960 → 736 on the detector, then the server → mobile detector choice, then
the recognition batch size.  Reach for a smaller *recognizer* last: recognition quality is
what the engine is buying.

Comparison points on the same hardware: one grounding call is ~1.0 s with the first line
painted at ~460 ms, and the retired sidecar architecture cost ~2.25 s per changed frame
(342 ms to read plus ~1.9 s for a separate batch translation).

---

## 3. Extracting Performance Metrics

To profile and optimize the local inference pipelines, developers can extract telemetry and statistics using several approaches:

### A. Lemonade API Statistics Endpoint
The embedded Lemonade server tracks metrics for active and past model invocations. You can query these directly using `curl`:
```bash
curl http://localhost:13305/v1/stats
```
This endpoint returns details such as:
* Time to First Token (TTFT)
* Output tokens/sec (throughput)
* Video Transformer (ViT) encoding duration
* Model memory and VRAM footprints

### B. MAGE Client Debug Logs
After each visual translation or chat inference run, the `InferenceWorker` automatically polls the stats endpoint in a fire-and-forget background task and logs the results.
To view these:
1. Launch MAGE with `DEBUG` logging via the `XIAN_LOG_LEVEL` environment variable (the default is `INFO`, which keeps the console readable):
   ```bash
   XIAN_LOG_LEVEL=DEBUG ./mage.sh
   ```
2. Scan the logs for the following message prefix:
   ```text
   DEBUG - mage.workers - Lemonade stats post-inference: {...}
   ```

### C. System and Hardware Diagnostics
To inspect underlying hardware status and engine mapping:
```bash
curl http://localhost:13305/v1/system-info
```

---

## 4. Screen Capture Pipelines

Capturing on-screen frames under Wayland introduces security and sandboxing complexities. MAGE optimizes region capture based on the environment:

| Compositor/OS | Capture Method | Latency Profile | Overhead Mitigations |
|---|---|---|---|
| **KDE Plasma** | `spectacle -b -n -f -o` | Medium | File writing cleanup, sub-process launch overhead. |
| **GNOME** | DBus Screenshot API | Low | Direct IPC, avoids spawning external binaries. |
| **Wayland (Generic)** | `grim -` | Very Low | Streamed directly to stdout, avoids disk write. |
| **X11 / Windows / macOS**| `QScreen.grabWindow` | Extremely Low | Native memory buffer capture. |

### Image Preprocessing
Before sending frame buffers to Lemonade, the client applies PIL-based optimizations to reduce token size and processing latency. This pipeline has been meticulously tuned to balance VLM throughput against OCR readability and should not be dynamically altered:
1. **Dimension Clamping**: Scaling inputs to keep maximum dimensions within VLM limits (e.g., 448px or 896px depending on model preference).
2. **Square Padding**: Padding non-square captures to a square format to prevent the Vision Transformer (ViT) from stretching and distorting text.
3. **PIL Sharpening**: A lightweight sharpening filter improves character edge contrast, reducing hallucination rates in OCR tasks.

---

## 5. Input Capture: Wayland evdev vs. User-space

Standard global hotkey capturing libraries rely on X11 grabs, which fail under Wayland due to display security measures.

* **EvdevHotkeyListener**:
  * Listens to raw input events under `/dev/input/` on a background thread.
  * *Requirement*: User must belong to the system `input` group to access the raw device descriptors.
* **Pynput Fallback**:
  * Used automatically if evdev fails or if running on non-Linux platforms (macOS/Windows).
