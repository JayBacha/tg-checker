SETUP (ek baar)
1. Python 3.9+ install karein.
2. Is folder mein terminal kholen:
     pip install -r requirements.txt
3. my.telegram.org par login karein -> "API development tools" -> app banayen -> API ID aur API Hash copy karein.
4. Chalayen:
     python app.py
5. Browser mein kholen:  http://127.0.0.1:5000
6. Pehli dafa API ID/Hash dalen, phir phone number, phir Telegram mein aaya code (aur agar 2-step password hai to wo).

USE
- List paste karein (har line mein @username ya +92... number), "Start check" dabayein.
- Results filter karein aur CSV download karein.

NOTES
- Delay kam na rakhein (2-3 sec theek hai), warna FloodWait ya restriction aa sakti hai.
- Phone number se check karne par tool temporary contact add karke wapas delete kar deta hai.
- Agar banda last seen hide kare to "Long time ago / hidden" dikhega; Telegram hidden aur purane ko alag nahi batata.
- Alag/secondary account use karein. Sirf apne jaiz kaam ke liye use karein.
- config.json aur tg_session aapke login data hain, kisi ke sath share na karein.
