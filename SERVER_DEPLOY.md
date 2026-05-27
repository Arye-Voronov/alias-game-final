# Alias AI Multiplayer Server

השרת הזה מנהל את מצב ה-Multiplayer:

- חדרים
- שחקנים
- מילה סודית
- רמזים פתוחים
- ניחושים
- ניקוד
- מעבר בין סבבים

במצב Multiplayer השחקנים לא מקבלים את המילה הסודית. היא נשארת רק בשרת.

## הרצה מקומית

```bash
python3 multiplayer_test_server.py
```

אם פורט 8000 תפוס:

```bash
python3 multiplayer_test_server.py --port 8010
```

במשחק מכניסים:

```text
http://127.0.0.1:8000
```

או את הפורט שבחרתם.

## הרצה באינטרנט

צריך להעלות לשרת האינטרנט לפחות את הקבצים:

```text
multiplayer_test_server.py
words.py
data.json
```

פקודת הרצה:

```bash
python3 multiplayer_test_server.py
```

השירות שמארח את השרת צריך לפתוח את משתנה הסביבה:

```text
PORT
```

הקוד כבר קורא אותו אוטומטית.

אחרי שהשרת עולה, שירות האחסון ייתן כתובת HTTPS, לדוגמה:

```text
https://alias-server.example.com
```

את הכתובת הזאת מכניסים במשחק בשדה:

```text
כתובת שרת
```

## קוד חדר

- קוד חדר ריק יוצר חדר חדש.
- קוד חדר מלא מצטרף לחדר קיים.

לדוגמה, שחקן ראשון מתחיל בלי קוד חדר ומקבל `4821`.
שחקן שני מכניס את אותו קוד חדר כדי להצטרף.

## בדיקת שרת

בדפדפן או ב-curl:

```bash
curl https://YOUR_SERVER/health
```

תשובה תקינה:

```json
{"status":"ok","rooms":0}
```

