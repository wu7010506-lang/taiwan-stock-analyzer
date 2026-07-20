# 公開網站部署

本專案已可部署為 Render Python Web Service。

## 免費公開版本

1. 將此資料夾放入 GitHub 儲存庫。
2. 登入 Render，選擇 **New > Blueprint**。
3. 連結該 GitHub 儲存庫，Render 會讀取 `render.yaml`。
4. 建立完成後會取得公開的 `https://...onrender.com` 網址。
5. 第一次進入網站後，先執行市場同步與建立選股資料集。

免費方案的檔案系統不是永久儲存空間，重新部署或服務重建時，SQLite
資料可能重置。免費服務一段時間無流量後也可能休眠，第一次開啟需等待啟動。

## 永久保存資料

若要永久保存「我的股票」、已同步行情與基本面資料，可在 Render 將方案改成
支援 Persistent Disk 的付費 Web Service，掛載到 `/var/data`，並將環境變數設為：

```text
DATABASE_PATH=/var/data/stocks.db
```

部署後可用 `/health` 確認服務狀態，回傳 `{"status":"ok"}` 即代表正常。
