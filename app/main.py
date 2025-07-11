# app/main.py
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings # config settings
from app.db.mongodb import db
from datetime import datetime
from app.api.v1.api import router as api_router # organizing api endpoints
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.chat import router as chat_router
from app.api.v1.endpoints.feedback import router as feedback_router


# Logging track events when program runs. Instead of using print() statements
# Output messages with different severity levels and destinations (console, files, etc.)
# Python logging has several levels (in increasing order of severity): DEBUG, INFO, WARNING, ERROR, CRITICAL
# The basicConfig() function also has other parameters (not used here): format, filename, filemode, etc.
logging.basicConfig(level=logging.INFO) 

# Create logger instance specific to this module(ie file): app.main.py - more granular control over logging by file 
logger = logging.getLogger(__name__) 

# Create FastAPI instance 
# Your app needs a way to talk to a server that handles all this logic and data storage. 
# FastAPI is like the waiter system that takes your requests and processes using the logic and data storage. 
app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
)

# CORS (Cross-Origin Resource Sharing) is a security feature in web browsers that prevents websites 
# from making requests to a different domain than the one that served the web page.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS, # The list of websites allowed to talk to our API
    allow_credentials=True,
    allow_methods=["*"], # HTTP methods (also called "verbs") define what action you want to perform on a resource. 
    allow_headers=["*"], # Additional pieces of info sent with HTTP, like metadata or instructions that accompany the main content. - content type, authorization, etc.
)

# Decorated functions that run when specific events occur in the application lifecycle
@app.on_event("startup")
async def startup_event():
    logger.info("Startup") #A typical log message might look like: INFO:app.main:Startup
    await db.connect_to_database() # Connect to MongoDB


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Shutdown")
    await db.close_database_connection()

@app.get("/health")
async def health_check():
    #logger.info("Health check endpoint hit")
    return {"status": "healthy"}


# A route is simply a URL path that your API responds to, 
# along with the function that handles requests to that path.
# Routers are a way to organize related routes together. Think of them like departments in a company.
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(feedback_router, prefix=f"{settings.API_V1_STR}/feedback", tags=["feedback"])