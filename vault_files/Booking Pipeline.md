---
tags: [dashboard, booking]
---

# 📸 Booking Pipeline

## 🔴 Need to Reply
```dataview
TABLE WITHOUT ID
  link(file.path, client) AS "Client",
  platform, shoot_type, date_discussed
FROM "2-Areas/Clients"
WHERE status = "need-to-reply"
SORT last_updated DESC
```

## 🟡 Waiting for Response
```dataview
TABLE WITHOUT ID
  link(file.path, client) AS "Client",
  platform, shoot_type, date_discussed
FROM "2-Areas/Clients"
WHERE status = "waiting"
SORT last_updated DESC
```

## 🟢 Confirmed Shoots
```dataview
TABLE WITHOUT ID
  link(file.path, client) AS "Client",
  platform, shoot_type, date_discussed, location
FROM "2-Areas/Clients"
WHERE status = "confirmed"
SORT date_discussed ASC
```

## ✅ Completed
```dataview
TABLE WITHOUT ID
  link(file.path, client) AS "Client",
  platform, shoot_type, date_discussed
FROM "2-Areas/Clients"
WHERE status = "completed"
SORT last_updated DESC
LIMIT 20
```

## 📊 Stats
```dataview
TABLE WITHOUT ID
  status AS "Status",
  length(rows) AS "Count"
FROM "2-Areas/Clients"
WHERE status != null
GROUP BY status
```
