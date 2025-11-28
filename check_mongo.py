from pymongo import MongoClient

client = MongoClient(MONGO_URI_ATLAS)

print("Bases dispo:", client.list_database_names())

db = client["scitools"]
print("Collections dans scitools:", db.list_collection_names())

col = db["articles"]
count = col.count_documents({})
print("Nb docs dans articles:", count)

if count > 0:
    for art in col.find().limit(2):
        print("ID:", art.get("article_id"), "Annotations:", art.get("annotations"))
