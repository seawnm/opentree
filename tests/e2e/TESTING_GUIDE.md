# E2E Testing Guide — Assertion Layering for AI Bot Tests

> **給 AI 的說明**：撰寫或修改 E2E 測試前，請先閱讀此文件。所有 E2E 測試必須遵循漏斗式分層模型。

## 核心原則

opentree 的 E2E 測試對象是一個由 Claude CLI 驅動的 Slack Bot。
AI 回覆具有**非確定性**（non-deterministic），因此測試的 assertion 設計
必須在「有效保護」和「避免 flaky」之間取得平衡。

### 漏斗式分層模型（Funnel Layering）

每個 E2E 測試的 assertion 應按照以下層級設計，**高層級 assertion 必須是 hard pass**：

| 層級 | 類型 | 確定性 | pytest 標記 | 範例 |
|------|------|--------|-------------|------|
| **L0** | 結構性 | 100% | 無（hard pass） | config 存在、JSON schema 正確、heartbeat 檔案存在 |
| **L1** | 行為性 | 95%+ | 無（hard pass） | bot 有回覆、回覆非空、回覆不含 unhandled error |
| **L2** | 語意性 | 70-90% | `xfail(strict=False)` | 回覆包含特定關鍵字、使用了正確工具 |
| **L3** | 精確性 | 30-60% | `xfail(strict=False)` 或 skip | 回覆完全符合預期格式、精確數值匹配 |

### 分層規則

1. **L0/L1 assertion 永遠不加 xfail** — 這些是 bot 的基本功能保證。如果 bot 連回覆都沒有，CI 必須紅燈。

2. **L2 assertion 可以用 xfail(strict=False)** — 但必須同時包含 L1 assertion 作為 hard pass 層。例如：
   ```python
   # L1: hard pass — bot 必須回覆
   reply = wait_for_bot_reply(thread_ts, timeout=120)
   assert reply, "Bot returned an empty reply"
   
   # L2: xfail — 語意檢查（AI 可能用不同措辭）
   # 此行可以在 xfail wrapper 內
   assert "keyword" in reply.lower()
   ```

3. **一個測試函式只測一個層級** — 如果需要同時驗證 L1 和 L2，拆成兩個測試。避免一個 xfail 測試中夾帶 L1 assertion（L1 的失敗會被 xfail 吃掉）。

4. **xfail 升級流程** — 當 xfail 測試在 CI 中連續穩定 XPASS（>10 次），應移除 xfail marker 升級為 hard pass，並在 CHANGELOG 記錄。

### Assertion 策略選擇

#### 推薦：keyword-list（contains-any）

```python
indicators = ["not found", "doesn't exist", "找不到", "不存在"]
found = any(ind in reply_lower for ind in indicators)
assert found, f"Expected error indication, got: {reply[:500]}"
```

**適用場景**：大多數 L2 assertion。
**優點**：deterministic、可維護、覆蓋多語言。
**維護**：遇到新的漏網措辭時，擴充 keyword list。

#### 選用：keyword-list + 反向 assertion

```python
# 正向：回覆應包含錯誤指示
assert any(ind in reply_lower for ind in error_indicators)
# 反向：回覆不應包含「成功」的跡象
assert "here is the content" not in reply_lower
```

**適用場景**：需要更高信心的 L2 assertion。

#### 不推薦：Y/N prefix prompt

```python
# ❌ 不推薦 — 不測試真實使用者路徑
send_message("以 Y/N 開頭回覆，檔案是否存在？")
assert reply.startswith("Y")
```

**原因**：E2E 測試的核心價值是驗證真實行為路徑。Y/N prefix 測試的是 AI 的指令遵從能力，不是 bot 的功能行為。

#### 保留：LLM-as-judge

```python
# 保留給未來高價值測試
judge_result = llm_judge(
    question="回覆是否正確描述了檔案不存在的情況？",
    response=reply,
)
assert judge_result.score >= 0.8
```

**適用場景**：L3 精確性驗證、需要語意理解的斷言。
**限制**：每次 assertion 多一次 API call，成本翻倍。目前暫不使用。

## xfail 使用規範

### 必須使用 `strict=False`

```python
@pytest.mark.xfail(
    strict=False,
    reason="具體說明為什麼這個測試可能失敗（AI 非確定性的具體面向）",
)
```

**為什麼不用 strict=True**：AI 非確定性測試的 XPASS 可能隨機發生，strict=True 會導致 CI 因「意外通過」而紅燈，產生假警報。

### xfail reason 必須具體

```python
# ✅ 好
reason="Memory write path depends on user_id resolution (message-tool sends as bot)"

# ❌ 差
reason="AI is non-deterministic"
```

### xfail 測試仍然計費

每個 xfail E2E 測試都會實際送 Slack 訊息 + 觸發 Claude CLI（timeout 120-180s）。
不要隨意新增 xfail 測試，除非它提供的覆蓋是其他 hard pass 測試無法取代的。

## 新增 E2E 測試的 checklist

- [ ] 確認測試屬於哪個層級（L0/L1/L2/L3）
- [ ] L0/L1 assertion 不加 xfail
- [ ] L2/L3 使用 `xfail(strict=False)` 且 reason 具體
- [ ] 使用 keyword-list 策略（非 Y/N prefix）
- [ ] Keyword list 涵蓋中英文同義詞
- [ ] Timeout 合理（simple: 120s, multi-turn: 180s, heavy: 300s）
- [ ] 測試函式包含 docstring 說明驗證目標和層級

## 現有測試分類（2026-04-05）

### Hard Pass（L0/L1）— ~66 個

基本功能保證，失敗 = CI 紅燈。涵蓋：
- Admin 指令、bot 啟動/關閉、事件分發
- 檔案讀取、session 儲存、安全防護（OWASP 20 項）
- UX 韌性（佇列、錯誤復原、circuit breaker）
- Token 統計、elapsed time 顯示

### xfail（L2/L3）— 10 個

AI 非確定性行為，不阻擋 CI。涵蓋：
- Memory：remember 指令寫入、記憶引用、heuristic 萃取（3 個）
- Session：跨 thread 隔離、3 輪上下文保持（2 個）
- Progress：工具 timeline 顯示、圖示正確、多工具聚合（3 個）
- Extensions：需求收集觸發、非需求不觸發（2 個）

### Skip — ~5 個

環境限制（Bot Walter 無 CLI 工具、DM 無法自動化）。
