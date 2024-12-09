from fastapi import FastAPI, File, UploadFile, Form, HTTPException, status, Depends, Request
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
import os
import httpx
import logging
from datetime import datetime
import joblib
import sqlite3
from typing import List
from pydantic import BaseModel
import sqlite3

def initialize_database():
    conn = sqlite3.connect("app.db")
    cursor = conn.cursor()
    
    # Create user_profiles table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            username TEXT NOT NULL,
            dob TEXT,
            categories TEXT,
            profession TEXT,
            profile_picture BLOB,
            additional_comments TEXT
        )
    ''')
    # Create admin table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL
        )
    ''')

    # Create user_interactions table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_interactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            video_id INTEGER,
            search_query TEXT,
            watched INTEGER,
            interaction_timestamp TEXT,
            FOREIGN KEY(user_id) REFERENCES user_profiles(id)
        )
    ''')

    cursor.execute('''
   CREATE TABLE IF NOT EXISTS video_ratings2 (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    video_id TEXT NOT NULL,
    rating INTEGER,
    liked BOOLEAN,
    UNIQUE(user_id, video_id)
);

    ''')

    conn.commit()
    conn.close()

initialize_database()

class RateVideoRequest(BaseModel):
    user_id: int
    video_id: str
    liked: bool = None
    rating: int = None # Optional liked
class RecordVideoInteraction(BaseModel):
    user_id: int
    video_id: str
    search_query: str = None
    watched: bool = False  

user_id_prev = 0
app = FastAPI()

# Load the trained model and interaction matrix
svd = joblib.load('svd_model.pkl')
interaction_matrix = joblib.load('interaction_matrix.pkl')

# Configure SQLite database connection
DATABASE_URL = "sqlite:///./app.db"

def create_connection():
    conn = sqlite3.connect("app.db")
    conn.row_factory = sqlite3.Row
    return conn

# YouTube API configuration
YOUTUBE_API_KEY = "AIzaSyCdrBM2PNQzamCRdL-FwHmPdiSFkTjW3tM"  # Replace with your actual API key
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3/search"

# Configure logging
logging.basicConfig(level=logging.INFO)
templates = Jinja2Templates(directory="templates")

@app.post("/rate-video")
async def rate_video(rating: RateVideoRequest):
    try:
        conn = create_connection()
        cursor = conn.cursor()
        print(user_id_prev)

        # Insert or update the user's rating or like for the video
        cursor.execute('''
            INSERT INTO video_ratings2 (user_id, video_id, rating, liked)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, video_id)
            DO UPDATE SET 
                rating = excluded.rating,
                liked = excluded.liked;

        ''', (user_id_prev, rating.video_id, rating.rating, rating.liked))

        conn.commit()
        cursor.close()
        conn.close()

        return {"message": "Rating/like recorded successfully"}
    except Exception as e:
        logging.error(f"Error in rate_video: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/filter-recommendations")
async def filter_recommendations(category: str = None, date: str = None):
    try:
        params = {
            "part": "snippet",
            "key": YOUTUBE_API_KEY,
            "maxResults": 10,
            "type": "video",
        }

        # Add filters to the API query
        if category:
            params["q"] = category
        if date:
            params["publishedAfter"] = date + "T00:00:00Z"  # Convert date to ISO format

        async with httpx.AsyncClient() as client:
            response = await client.get(YOUTUBE_API_URL, params=params)
            response.raise_for_status()
            data = response.json()

        return {"videos": data.get("items", [])}
    except Exception as e:
        logging.error(f"Error in filter_recommendations: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/analytics")
async def get_analytics():
    try:
        conn = create_connection()
        cursor = conn.cursor()

        # Query for most searched queries
        cursor.execute('''
            SELECT search_query, COUNT(*) as count
            FROM user_interactions
            WHERE search_query IS NOT NULL
            GROUP BY search_query
            ORDER BY count DESC
            LIMIT 10
        ''')
        top_searches = cursor.fetchall()

        # Query for popular videos
        cursor.execute('''
            SELECT video_id, COUNT(*) as views
            FROM user_interactions
            WHERE watched = 1
            GROUP BY video_id
            ORDER BY views DESC
            LIMIT 10
        ''')
        popular_videos = cursor.fetchall()

        conn.close()

        return {
            # "top_searches": [{"query": row["search_query"], "count": row["count"]} for row in top_searches],
            "popular_videos": [{"video_id": row["video_id"], "views": row["views"]} for row in popular_videos],
        }
    except Exception as e:
        logging.error(f"Error in get_analytics: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)


@app.get("/index")
async def read_root():
    file_path = "templates/index.html"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    else:
        return {"error": "File not found"}

@app.post("/submit-profile")
async def submit_profile(
    full_name: str = Form(...),
    email: str = Form(...),
    username: str = Form(...),
    dob: str = Form(...),
    categories: List[str] = Form(...),
    profession: List[str] = Form(...),
    additional_comments: str = Form(...),
    profile_picture: UploadFile = File(None)
):
    try:
        conn = create_connection()
        cursor = conn.cursor()

        # Read profile picture if it exists
        profile_picture_data = None
        if profile_picture:
            profile_picture_data = profile_picture.file.read()

        # Convert lists to comma-separated strings
        categories_str = ','.join(categories)
        profession_str = ','.join(profession)

        # Insert data into the database
        cursor.execute('''
            INSERT INTO user_profiles (full_name, email, username, dob, categories, profession, profile_picture, additional_comments)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (full_name, email, username, dob, categories_str, profession_str, profile_picture_data, additional_comments))

        conn.commit()
        cursor.close()
        conn.close()

        # Redirect to video.html after successful submission
        return RedirectResponse(url="/", status_code=303)
    except Exception as e:
        logging.error(f"Error in submit_profile: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/recommendations")
async def get_recommendations(query: str):
    try:
        # Construct the URL for the YouTube API
        params = {
            "part": "snippet",
            "q": query,
            "key": YOUTUBE_API_KEY,
            "maxResults": 5,
            "type": "video"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(YOUTUBE_API_URL, params=params)
            response.raise_for_status()
            video_data = response.json()

            if 'error' in video_data:
                return JSONResponse(content={"error": video_data['error']['message']}, status_code=response.status_code)
            # print(video_data)
            # Extract video information
            videos = video_data.get('items', [])
            video_items = [
                {
                    'title': video['snippet']['title'],
                    'description': video['snippet']['description'],
                    'thumbnail': video['snippet']['thumbnails']['default']['url'],
                    'video_id': video['id']['videoId']
                }
                for video in videos
            ]

            return {"items": video_items}
    except Exception as e:
        logging.error(f"Error in get_recommendations: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/search")
async def search_videos(query: str, pageToken: str = "", maxResults: int = 10):
    params = {
        "part": "snippet",
        "q": query,
        "key": YOUTUBE_API_KEY,
        "maxResults": maxResults,
        "pageToken": pageToken,
        "type": "video"
    }

    try:
        conn = create_connection()
        cursor = conn.cursor()
        global user_id_prev
        watched_value = 0

        cursor.execute('''
            INSERT INTO user_interactions (user_id, video_id, search_query, watched, interaction_timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (user_id_prev, "0", query, watched_value, datetime.now()))
        async with httpx.AsyncClient() as client:
            response = await client.get(YOUTUBE_API_URL, params=params)
            response.raise_for_status()
            data = response.json()

            if 'error' in data:
                return JSONResponse(content={"error": data['error']['message']}, status_code=response.status_code)
            # print(data)
            return JSONResponse(content=data)
    except httpx.HTTPStatusError as http_error:
        logging.error(f"HTTP Error: {str(http_error)}")
        return JSONResponse(content={"error": str(http_error)}, status_code=http_error.response.status_code)
    except Exception as e:
        logging.error(f"Unexpected Error: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/video")
async def serve_video(user_id: int, profession: str):
    try:
        logging.info(f"Received request with user_id: {user_id}, profession: {profession}")
        global user_id_prev 
        user_id_prev = user_id
        # global user_id_prev 
        profession_queries = {
            "Teacher": "education",
            "Student": "student",
            # Add more professions and queries as needed
        }
        
        query = profession_queries.get(profession, "popular")

        params = {
            "part": "snippet",
            "q": query,
            "key": YOUTUBE_API_KEY,
            "maxResults": 5,
            "type": "video"
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(YOUTUBE_API_URL, params=params)
            response.raise_for_status()
            video_data = response.json()

            if 'error' in video_data:
                return JSONResponse(content={"error": video_data['error']['message']}, status_code=response.status_code)

            videos = video_data.get('items', [])
            video_items = [
                {
                    'title': video['snippet']['title'],
                    'description': video['snippet']['description'],
                    'thumbnail': video['snippet']['thumbnails']['default']['url'],
                    'video_id': video['id']['videoId']
                }
                for video in videos
            ]

            file_path = r"templates/video.html"  # Ensure this path is correct
            if os.path.exists(file_path):
                with open(file_path, 'r') as file:
                    html_content = file.read()
                    html_content = html_content.replace("{{videos}}", str(video_items))
                return HTMLResponse(content=html_content)
            else:
                return JSONResponse(content={"error": "File not found"}, status_code=404)

    except Exception as e:
        logging.error(f"Error in serve_video: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/")
async def login_form():
    file_path = "/Users/shoaibm1/Downloads/userProfiling/templates/login.html"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    else:
        return {"error": "File not found"}

@app.post("/login")
async def login(username: str = Form(...), email: str = Form(...)):
    try:
        if username=="admin" and email == "admin@gmail.com":
            return RedirectResponse(url="/admin", status_code=303)
        conn = create_connection()
        cursor = conn.cursor()
        # cursor.execute('''
        #     SELECT id FROM admin WHERE name = ? AND email = ?
        # ''', (username, email))
        # admin = cursor.fetchone()
        
        # if admin:
        #     cursor.close()
        #     conn.close()
        #     return RedirectResponse(url="/admin", status_code=303)
        cursor.execute('''
            SELECT id, profession FROM user_profiles
            WHERE username = ? AND email = ? 
        ''', (username, email))
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user:
            user_id, profession = user
            # await record_interaction(user_id=user_id, video_id=None, search_query=None, watched=False)

            return RedirectResponse(url=f"/video?user_id={user_id}&profession={profession}", status_code=303)
        else:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    except Exception as e:
        logging.error(f"Error in login: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.post("/record_interaction")
async def record_interaction(record:RecordVideoInteraction):
    try:
        conn = create_connection()
        cursor = conn.cursor()

        watched_value = 1 

        cursor.execute('''
            INSERT INTO user_interactions (user_id, video_id, search_query, watched, interaction_timestamp)
            VALUES (?, ?, ?, ?, ?)
        ''', (record.user_id, record.video_id, record.search_query, watched_value, datetime.now()))

        conn.commit()
        cursor.close()
        conn.close()

        return {"message": "Interaction recorded successfully"}
    except Exception as e:
        logging.error(f"Error in record_interaction: {str(e)}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request):
    conn = create_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT full_name, email, username, dob, categories, additional_comments, profession
        FROM user_profiles
    """)
    rows = cursor.fetchall()
    conn.close()
    
    # Convert rows to a list of dictionaries
    users = [
        {
            "full_name": row["full_name"],
            "email": row["email"],
            "username": row["username"],
            "dob": row["dob"],
            "categories": row["categories"],
            "additional_comments": row["additional_comments"],
            "profession": row["profession"]
        }
        for row in rows
    ]
    
    return templates.TemplateResponse("admin.html", {"request": request, "users": users})

@app.get("/admin/update/{username}", response_class=HTMLResponse)
async def update_user_form(request: Request, username: str):
    try:
        conn = create_connection()
        cursor = conn.cursor()
        
        # Fetch the user profile with the specified username
        cursor.execute("""
            SELECT full_name, email, username, dob, categories, additional_comments, profession
            FROM user_profiles
            WHERE username = ?
        """, (username,))
        row = cursor.fetchone()
        conn.close()

        if row:
            user = {
                "full_name": row[0],
                "email": row[1],
                "username": row[2],
                "dob": row[3],
                "categories": row[4],
                "additional_comments": row[5],
                "profession": row[6]
            }
            return templates.TemplateResponse("update_user.html", {"request": request, "user": user})
        else:
            raise HTTPException(status_code=404, detail="User not found")
    except Exception as e:
        logging.error(f"Error in update_user_form: {str(e)}")
        raise HTTPException(status_code=500, detail="Server error while fetching user data.")

@app.post("/admin/update/{username}")
async def update_user(username: str, full_name: str = Form(...), email: str = Form(...), dob: str = Form(...),
                      categories: str = Form(...), additional_comments: str = Form(...), profession: str = Form(...)):
    try:
        conn = create_connection()
        cursor = conn.cursor()
        
        # Update the user profile with the specified username
        cursor.execute("""
            UPDATE user_profiles
            SET full_name = ?, email = ?, dob = ?, categories = ?, additional_comments = ?, profession = ?
            WHERE username = ?
        """, (full_name, email, dob, categories, additional_comments, profession, username))
        conn.commit()
        conn.close()

        return RedirectResponse(url="/admin", status_code=303)
    except Exception as e:
        logging.error(f"Error in update_user: {str(e)}")
        raise HTTPException(status_code=500, detail="Server error while updating user data.")

@app.get("/admin/delete/{username}")
async def delete_user(username: str):
    try:
        conn = create_connection()
        cursor = conn.cursor()
        
        # Delete the user profile with the specified username
        cursor.execute("""
            DELETE FROM user_profiles
            WHERE username = ?
        """, (username,))
        conn.commit()
        conn.close()

        return RedirectResponse(url="/admin", status_code=303)
    except Exception as e:
        logging.error(f"Error in delete_user: {str(e)}")
        raise HTTPException(status_code=500, detail="Server error while deleting user.")
    
    
@app.get("/")
async def login_form():
    file_path = "templates/login.html"
    if os.path.exists(file_path):
        return FileResponse(file_path)
    else:
        return {"error": "File not found"}