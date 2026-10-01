# ibus-proofread

A local proofreading demo using **unsloth/Gemma-4-E2B-it Q4_K_M**, llama.cpp with Vulkan, and an **800 ms typing debounce**. It includes a standalone GTK sandbox and a temporary IBus input method for GNOME/Wayland.

## Try the sandbox

Run inside your graphical session:

```sh
cd ~/Documents/projects/ibus-proofread
nix run . -- demo
```

Type `Ich habe dise Nachicht geschriben.` and pause. After 800 ms without changes, local inference starts. Its runtime is added to that delay. The corrected text appears below the editor; **Tab** or the accept button applies it. **Escape** dismisses it. Closing the window stops the owned inference server.

The sandbox checks its entire editor contents, up to 1200 characters. Cursor changes reschedule checking; leaving the editor discards suggestions and outstanding results.

## Try the IBus input method

```sh
nix run . -- ibus
```

Wait for `IBus demo active`, then focus an editable field in an application using IBus. The engine is registered and activated for this process's lifetime; it does not install a persistent GNOME input source or change your saved input-source settings. GNOME input-source switching can switch away from the demo.

- Printable characters and spaces build an underlined **preedit composition**.
- After an 800 ms pause, a correction appears in the IBus candidate popup.
- **Tab** or clicking the candidate commits the correction.
- **Enter** commits the original composition and passes Enter to the application.
- **Escape** dismisses the suggestion without losing the original composition.
- **Backspace** edits the composition. Navigation and modifier shortcuts commit the original before passing through.
- Focus loss asks the application to commit original preedit, never an unconfirmed correction.
- Fields reported by the application as password, PIN or private bypass the engine.

Stop with **Ctrl+C in the launching terminal**. On normal shutdown, the previous IBus engine is restored if the demo is still active. A forced kill cannot run that cleanup; switch to your normal input source if necessary.

This is a composition-based demo, not an editor for previously committed or selected text. The simple engine has no dead-key composition support. Application integration depends on IBus/preedit support; the isolated D-Bus path is tested, but this does not establish compatibility with every GNOME application or browser field.

## Model and inference

The first launch downloads the text GGUF (approximately 3.1 GB) from:

- Repository: `unsloth/gemma-4-E2B-it-GGUF`
- Revision: `0314792d7f1f7e229411f620751375812bb9faf2`
- File: `gemma-4-E2B-it-Q4_K_M.gguf`

It is cached under `${XDG_DATA_HOME:-~/.local/share}/ibus-proofread/REVISION/`. Downloads are atomic. No vision/audio projector is needed for this text-only demo. The Nix flake pins dependencies, including a Vulkan-enabled llama.cpp. GPU offload is requested; llama.cpp may fall back to CPU on other hardware.

Each launch owns one loopback-only server with a random API key. Typed text is sent only to that local server; it is not uploaded to Hugging Face. Server diagnostics use a temporary log, removed on shutdown. Suggestions are not automatically applied and can still contain model mistakes.

Only one inference runs at a time, with at most one latest debounced request queued. Text changes and focus loss invalidate older results. Inference failures preserve the original text.

Other commands:

```sh
nix run . -- download
printf 'Ich habe dise Nachicht geschriben.' | nix run . -- check
nix run . -- demo --model /path/to/model.gguf
nix run . -- --help
```

## Tests

```sh
nix develop --command python tests/run.py
# Include real model/GPU inference in the GTK test:
PROOFREAD_TEST_MODEL=1 nix develop --command python tests/run.py
```

The runner owns a virtual X display and a private session bus/IBus daemon. It does not inject keys into the real desktop. Tests cover debounce replacement, stale-result invalidation, bounded queuing, failures, GTK suggestion acceptance/dismissal, and real IBus activation/key processing/candidate commits/private fields. The real-model test expects the cached default GGUF; run `download` first.

## Flow

```text
composition changed:
    invalidate old suggestion and results
    restart the 800 ms timer

timer fires:
    send a versioned snapshot to local inference off the UI thread

result arrives:
    if snapshot is still current:
        display suggestion
    otherwise:
        discard it
```
