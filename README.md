# Kelly 每日 Instagram 圖片貼文

每日香港時間 **20:00**，GitHub Actions 會為翌日產生一張固定虛構 AI 人物的生活照及繁體中文文案，並透過 Buffer 指定 **@kellykellyhk3** 在翌日 **11:00（香港時間）** 發佈單張圖片貼文。電腦毋須長期開機。

## 啟用

1. 確認 GitHub repository 是 `andylee2305/member-club-auto`，而且是 **public**。Buffer 必須在發佈時從公開網址讀取圖片。
2. 在 GitHub repository 的 **Settings → Secrets and variables → Actions → New repository secret** 分別加入：
   - `OPENAI_API_KEY`：有圖片編輯模型及文案模型存取權的 OpenAI API key。
   - `BUFFER_API_KEY`：**連接 @kellykellyhk3 的另一個 Buffer 帳戶**之個人 API key。不要使用目前連接到 `@ai_andy_lee` 的 Buffer 授權。
3. 在 Buffer 確認 `@kellykellyhk3` 是可自動發佈圖片的 Instagram 專業帳戶，並保持連線有效。
4. 到 **Actions → Daily Instagram photo → Run workflow** 手動執行一次作初次檢查；可填寫未來的香港日期，留空即安排翌日。然後查看該日貼文是否出現在 Buffer 排程。

**請勿將 API key 放進聊天、程式碼、工作流程檔案或提交紀錄。**

## 流程

- 工作流程先查詢 Buffer 帳戶及頻道，只接受名稱與 `kellykellyhk3` 完全一致的 Instagram 頻道；找不到或有重複便停止，避免發錯帳戶。
- 使用 `assets/reference/` 四張人物相作身份參考，由 OpenAI 產生新的 4:5 生活照及廣東話語氣文案。每次輪換場景。輸出圖片及 JSON 紀錄放在 `posts/`。
- GitHub 提交圖片後，以該提交的公開、固定網址交給 Buffer。排程使用 UTC `03:00`，即香港 `11:00`。
- 貼文設為 Instagram `post`、`automatic`，並設定 Buffer 的 `isAiGenerated: true`。文案亦附 `#AI創作`。
- 重跑同一日期時會重用已有圖片及文案，查找該時段的 Buffer 貼文，避免重複排程。若該時段有不同貼文便停止供人工檢查。

## 本機檢查

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

本機 `preflight` 需要 `BUFFER_API_KEY` 環境變數；`generate` 需要 `OPENAI_API_KEY`。請勿把包含 key 的 `.env` 檔提交到 GitHub。

## 運作注意

- GitHub Actions 的定時觸發可能延遲；提前一晚產生及排程，讓 Buffer 在指定時間發佈。首次成功排程前，這不是已啟用的每日自動發佈。
- 如果 GitHub Actions 或 Buffer 發佈失敗，查看 Actions 執行紀錄及 Buffer 貼文狀態，修正後用相同 `target_date` 手動重跑。
- `posts/` 圖片及 `assets/reference/` 參考相會在 public repo 公開；不要放入不想公開的素材。
- 每日圖片會令 Git repository 持續增長。長期運作後可改用專門圖片儲存服務。
- OpenAI API 會按模型、圖片品質及用量收費。預設文案模型依次試 `gpt-4o-mini`、`gpt-4.1-mini`；圖片模型依次試 `gpt-image-2.5-sunburst`、`gpt-image-1.5`、`gpt-image-1`。只有模型存取被拒時才試下一個。可用 `OPENAI_TEXT_MODEL` / `OPENAI_IMAGE_MODEL` 環境變數指定逗號分隔的候選模型。
