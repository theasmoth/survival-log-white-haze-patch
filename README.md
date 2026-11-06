# Survival Log: missing menu in CrossOver on Mac

**Symptoms:** the menu scene and music work, but UI buttons are missing.

**Workaround:** disable Vuplex accelerated paint with a one-byte DLL patch. In the tested installation, the menu appeared and buttons worked. Repeated Chromium errors `Unable to initialize SkSurface` and `Already being accessed for write` disappeared.

Tested: Apple M4 Pro, macOS 26.6.1, CrossOver 26.3, Windows 10 64-bit bottle, **DXMT**, Survival Log 1.1.20151, Unity 6000.2.7f2, Vuplex 4.13.

Experimental workaround. Only the exact DLL hash below is supported. Extended gameplay was not tested. The tested installation already had a separate Unity patch, `UNITY_SL-7E0 v1`; this script does not install it.

## Apply

Requires **macOS and Python 3.9+**. No dependencies or `sudo`.

1. Download this repository and open Terminal in its folder.
2. **Fully close the game and its `Vuplex WebView.vuplex` processes before patching or restoring.** Keep them closed until the command finishes. The script does not check whether the game is running.
3. Run the patcher. It finds the supported DLL automatically:

```bash
python3 patch_vuplex.py status
python3 patch_vuplex.py patch --dry-run
python3 patch_vuplex.py patch
```

Search covers C: drives inside `~/Library/Application Support/CrossOver/Bottles`. It skips Windows system directories and directory symlinks. It checks the game layout, executable, and exact DLL hash. It never scans your whole home directory.

If multiple supported installations are found, no file is changed. Select the installation you launch:

```bash
python3 patch_vuplex.py patch --dll "/path/to/VuplexWebViewWindows.dll"
```

For custom bottle storage:

```bash
python3 patch_vuplex.py patch --bottles-dir "/path/to/Bottles"
```

If discovery cannot finish, the script stops. Use `--dll` for installations outside bottle C: drives.

States: `original` = supported; `patched` = already patched; `unknown` = unsupported, stop.

The script saves `VuplexWebViewWindows.dll.original.bak` beside the DLL. An existing backup is reused only if it exactly matches the verified original. It is never overwritten. Patch, rollback, and patch again work with the same backup. A mismatched backup stops the operation. Use `--backup /path/to/new-backup.bak` to choose another location.

Launch from the same bottle. The tested launch used:

```bash
/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine \
  --bottle bottle_name \
  --workdir 'C:\Survival Log' \
  'C:\Survival Log\SurvivalLog.exe' \
  -force-d3d11 -logFile 'C:\survival-log-player.log'
```

Adjust paths as needed. This command does not select DXMT; check your bottle settings separately.

## Verify

Fully restart the game after patching. Check embedded Chromium:

```bash
ps -ww -axo pid,ppid,command | grep '[V]uplex WebView.vuplex'
```

The **main process, without `--type=...`**, must contain `--vx-accelerated-paint-disabled`. The DLL supplies this flag; adding it to Unity launch arguments is not equivalent.

Confirm the menu appears and buttons respond. If the flag is missing, check the loaded DLL path:

```bash
lsof -nP 2>/dev/null | grep -F 'VuplexWebViewWindows.dll'
```

Look for the game process pointing to your patched file. Missing output is inconclusive.

Fresh logs inside the bottle:

```text
C:\survival-log-player.log
C:\users\crossover\AppData\LocalLow\LLS\SLGame\webui-chromium-log.txt
```

On macOS, look under the bottle's `drive_c/`. The Windows username may differ. Successful HTML loading alone does not prove the UI renders. `DCompositionCreateDevice3` errors remained in the working run.

## Roll back

Close the game and its Chromium processes. Automatic discovery also works for rollback:

```bash
python3 patch_vuplex.py restore --dry-run
python3 patch_vuplex.py restore
```

For a custom installation, pass the same `--dll PATH` or `--bottles-dir PATH`. For a custom backup, pass the same `--backup PATH`. Restoration requires a verified original backup and retains it afterward.

## Patch details and options

File: `SurvivalLog_Data/Plugins/x86_64/VuplexWebViewWindows.dll`, **411464 bytes**.

- File offset `0xF505`: `F1` becomes `00`.
- Original SHA-256: `1c74ee9ed70ec086e4230573511636097eb8d4f6d9f51f64d93174edaad59ea8`
- Patched SHA-256: `87bae34bf4b295b1a48e40d21f9259405752b9573436785d65dbba504bdf79d2`

The change makes an existing code block add `--vx-accelerated-paint-disabled` when launching Chromium. It does not modify HTML or bottle settings. The exact underlying Chromium/DXMT defect remains unisolated.

**The patch invalidates the DLL's original digital signature.** Disabling accelerated paint may affect performance. Game updates may replace the DLL; check its hash before reapplying.

```bash
python3 patch_vuplex.py --help
```

Supported options: `--bottles-dir`, `--dll`, `--backup`, `--dry-run`, `--offset`, `--before`, `--after`, `--original-sha256`, `--patched-sha256`.

The verified patch parameters are defaults. Custom parameters require separate binary analysis. Never change hashes just to bypass an unsupported-version error. There is no `--force` option.

The script checks hashes, bytes, and backups before writing. It does not inspect or stop processes. Replacement is atomic and preserves POSIX permission bits, but not extended attributes or ACLs. Symlinks and hard-linked DLLs are rejected.

If the flag is present but the menu remains missing, save fresh logs before changing anything else. Compare one factor at a time, such as the graphics backend. This workaround is not verified for other configurations.

## Tests and sources

```bash
python3 -m unittest discover -v
```

Tests use temporary files, not the installed game. Patching and rollback were also verified on a temporary copy of the supported DLL.

- [Vuplex API](https://developer.vuplex.com/webview/StandaloneWebView#SetAcceleratedPaintEnabled)
- [Vuplex hardware acceleration](https://support.vuplex.com/articles/standalone-hardware-acceleration/)
- [Similar CrossOver report](https://www.codeweavers.com/compatibility/crossover/forum/survival-log/?msg=362953)

Publish source files only. Do not include game DLLs, backups, or personal logs. Nothing is uploaded automatically.
