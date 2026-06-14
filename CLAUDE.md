# CLAUDE.md

本專案的 AI 協助安裝與使用劇本統一維護在 **[AGENTS.md](AGENTS.md)**，請以該檔為準。

協助使用者前，請務必先讀 [AGENTS.md](AGENTS.md) 的「第 0 節：鐵則」——這是一套會碰到**真實金錢**的台股下單程式：

- 絕不主動開啟實單（保持 `YUANTA_ENV=UAT`、`YUANTA_ENABLE_ORDER=NO`）。
- 絕不印出或 commit 任何機密（`.env`、`frontend/.env`、`*.pfx`、API 金鑰）。
- 券商 SDK 不在 repo 內，需引導使用者自行下載。
- 建議新使用者先玩「模擬沙盒」（免帳密/憑證/SDK）再接真實券商。
