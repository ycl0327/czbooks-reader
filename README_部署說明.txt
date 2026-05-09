CZBooks iPhone 雲端部署版

檔案內容：
- app.py：Flask 後端，負責抓取 CZBooks 章節
- templates/index.html：iPhone Safari 前端
- requirements.txt：Render 需要安裝的套件
- render.yaml：Render 一鍵部署設定
- Procfile：雲端啟動指令

Render 部署方法：
1. 註冊 GitHub：https://github.com
2. 建立一個新的 Repository，例如 czbooks-iphone-reader
3. 把這個資料夾內所有檔案上傳到 Repository 根目錄
4. 註冊 Render：https://render.com
5. Render 選 New + → Blueprint
6. 連接剛剛的 GitHub Repository
7. Render 會讀取 render.yaml，自動部署
8. 部署完成後，打開 Render 給你的網址，例如：
   https://czbooks-iphone-reader.onrender.com
9. iPhone Safari 開這個網址
10. 按分享 → 加入主畫面

本機測試方法：
1. 在資料夾內開 PowerShell
2. 執行：pip install -r requirements.txt
3. 執行：python app.py
4. 電腦開：http://127.0.0.1:5000

注意：
- Render 免費版閒置後會休眠，第一次開可能要等 30 秒以上。
- 若 CZBooks 網站改版或封鎖雲端 IP，抓取可能會失敗。
