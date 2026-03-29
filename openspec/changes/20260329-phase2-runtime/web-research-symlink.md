# Web Research: Python Symlink Management Cross-Platform
Date: 2026-03-29
Keywords: ["Python", "symlink", "WSL2", "NTFS", "os.symlink", "junction", "fallback", "cross-platform"]

## Source 1: Trail of Bits — Why Windows Can't Follow WSL Symlinks
- URL: https://blog.trailofbits.com/2024/02/12/why-windows-cant-follow-wsl-symlinks/
- Relevance: HIGH
### Key Excerpts
> Symlinks on Linux are implemented differently than symlinks on Windows: on Windows, a symlink is an object, implemented and interpreted by the kernel. On Linux, a symlink is simply a file with a special flag, whose content is a path to the destination.
> WSL creates "LX symlinks" — a Linux-native format that Windows cannot process, resulting in `STATUS_IO_REPARSE_TAG_NOT_HANDLED` errors when accessed from the Windows side.
> Windows-created symlinks work seamlessly in both Windows and WSL. WSL-created symlinks function within WSL only; inaccessible from Windows.
> Hard links created by WSL function normally on Windows. NTFS junctions created on Windows are accessible from WSL.
> Windows could follow WSL's symlinks when they were created with a relative path but not with an absolute path — though this wasn't reproducible universally.
### Takeaways
- WSL 建立的 symlink（LX symlinks）Windows 讀不到
- Windows 建立的 symlink 在 WSL 和 Windows 都能讀
- Hard link 跨邊界可正常工作
- NTFS junction（Windows 建立）在 WSL 可存取
- 相對路徑 symlink 可能在某些環境下跨邊界可用，但不穩定

## Source 2: WSL GitHub Issue #4357 — NTFS Symlinks Break PATH
- URL: https://github.com/microsoft/WSL/issues/4357
- Relevance: MEDIUM
### Key Excerpts
> When WSL2 encounters NTFS symlinks in the $PATH, command execution fails with EPERM instead of ENOENT.
> glibc's `execvpe()` states that EACCES errors should trigger continued PATH searching, but EPERM errors trigger immediate abortion. WSL incorrectly returns EPERM.
### Takeaways
- NTFS symlink 在 WSL2 PATH 中會觸發 EPERM 錯誤
- 這是 WSL 層面的 bug（已 closed 2024-02）
- 使用 symlink 時需注意可能的 EPERM 問題

## Source 3: WSL GitHub Issue #8385 — Windows Symlinks Pointing to WSL
- URL: https://github.com/microsoft/WSL/issues/8385
- Relevance: MEDIUM
### Key Excerpts
> Windows symlinks (mklink) pointing to `\\wsl$\...` paths should resolve in WSL but don't always work reliably.
### Takeaways
- 跨 WSL/Windows 邊界的 symlink 解析仍有未解決的邊界情況
- 不應依賴跨邊界 symlink 作為可靠機制

## Source 4: Python os.symlink() Method Guide
- URL: https://thelinuxcode.com/python-ossymlink-method-a-practical-production-focused-guide/
- Relevance: HIGH
### Key Excerpts
> On Windows, `os.symlink()` behavior depends on system policy, developer mode, and privileges.
> Creating symlinks can fail with PermissionError if the process does not have the needed rights.
> Use `target_is_directory=True` parameter on Windows for directory symlinks.
### Takeaways
- Windows 上 `os.symlink()` 需要 Developer Mode 或特殊權限
- WSL2 在 NTFS 上建立的 symlink 行為不同於原生 Linux
- 需要 `target_is_directory` 參數來區分檔案和目錄 symlink

## Source 5: PEP 778 — Supporting Symlinks in Wheels
- URL: https://peps.python.org/pep-0778/
- Relevance: LOW
### Key Excerpts
> PEP 778 proposes supporting symlinks in Python wheels, acknowledging cross-platform complexity.
### Takeaways
- Python 生態系統對 symlink 的跨平台支援仍在演進中

## Source 6: Rob Pomeroy — WSL2 Filesystem Performance
- URL: https://pomeroy.me/2023/12/how-i-fixed-wsl-2-filesystem-performance-issues/
- Relevance: MEDIUM
### Key Excerpts
> Store files on WSL's Linux filesystem (VHDX) instead of Windows NTFS via /mnt paths to avoid performance issues.
> Move working files from /mnt/c paths to native Linux filesystem for better performance.
### Takeaways
- 在 WSL2 上，/mnt/c 等 NTFS 路徑效能極差
- 最佳做法是將工作檔案放在 WSL 原生 Linux 檔案系統上
- 但 OpenTree 的目標場景是管理 Windows 磁碟上的專案，無法完全避免 NTFS

## Summary

WSL2 + NTFS 環境下的 symlink 管理是 OpenTree 的核心挑戰之一。研究結論：

### Symlink 相容性矩陣

| 建立方 | 建立位置 | WSL 可讀？ | Windows 可讀？ |
|--------|----------|-----------|---------------|
| WSL `os.symlink()` | Linux FS (ext4) | YES | NO |
| WSL `os.symlink()` | NTFS (/mnt/c) | YES | NO (LX symlink) |
| Windows `mklink` | NTFS | YES | YES |
| Windows `mklink /J` (junction) | NTFS | YES | YES |
| Hard link | NTFS | YES | YES |

### 推薦的 Fallback 策略（OpenTree Phase 2）

1. **首選**：`os.symlink()`（Linux/macOS 原生、WSL ext4 檔案系統）
2. **Fallback 1**：NTFS Junction（`mklink /J`，目錄專用，WSL 透過 `subprocess` 呼叫 `cmd.exe /c mklink /J`）
3. **Fallback 2**：Hard link（`os.link()`，檔案專用，不適用於目錄）
4. **Fallback 3**：File copy（`shutil.copytree()`，最可靠但佔用空間）

### 實作建議

```python
def create_link(source: Path, target: Path) -> LinkResult:
    """Create symlink with cross-platform fallback."""
    # 1. Try symlink
    try:
        os.symlink(source, target, target_is_directory=source.is_dir())
        return LinkResult(method="symlink", success=True)
    except (OSError, PermissionError):
        pass

    # 2. Try junction (Windows/WSL NTFS, directories only)
    if source.is_dir() and is_ntfs(target):
        try:
            # cmd.exe /c mklink /J ...
            return LinkResult(method="junction", success=True)
        except:
            pass

    # 3. Fallback to copy
    shutil.copytree(source, target) if source.is_dir() else shutil.copy2(source, target)
    return LinkResult(method="copy", success=True)
```

### 注意事項

- WSL2 NTFS 上的 symlink 效能不佳，應盡量避免大量 I/O
- Junction 只支援目錄，不支援檔案
- Hard link 不支援目錄，不支援跨 filesystem
- 需要記錄使用的連結方式，以便後續維護（refresh/remove 邏輯不同）
