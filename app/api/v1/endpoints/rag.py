# app/api/v1/endpoints/rag.py
import logging
import os
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form, status
from app.core.security import get_current_admin_user
from app.models.admin import Admin
from app.services.openai_service import OpenAIService
from app.db.mongodb import db
from datetime import datetime
from bson import ObjectId 

router = APIRouter()
logger = logging.getLogger(__name__)

def get_openai_service():
    return OpenAIService()

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    vector_store_name: Optional[str] = Form(None),
    current_admin: Admin = Depends(get_current_admin_user),
    openai_service: OpenAIService = Depends(get_openai_service)
):
    """
    Upload a file to OpenAI and attach it to a vector store.
    The vector store will be attached to the admin's assistant.
    """
    logger.info(f"File upload request received: {file.filename}")
    
    try:
        # Read file contents
        contents = await file.read()
        file_size = len(contents)
        
        # Check file size (OpenAI limit is 512MB)
        if file_size > 512 * 1024 * 1024:  # 512MB in bytes
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File size exceeds the 512MB limit"
            )
            
        # Create a temporary file
        temp_file_path = f"/tmp/{file.filename}"
        with open(temp_file_path, "wb") as f:
            f.write(contents)
            
        # Upload file to OpenAI
        openai_file = await openai_service.upload_file(
            temp_file_path,
            purpose="assistants"
        )
        
        # Clean up temporary file
        os.remove(temp_file_path)
        
        # Define vector store name or use default
        vs_name = vector_store_name or f"{current_admin.username}'s Vector Store"
        
        # Check if admin already has a vector store
        admin_data = await db.db.admin_users.find_one({"_id": current_admin.id})
        
        if not admin_data:
            logger.info(f"Admin not found by string ID, trying ObjectId")
            admin_data = await db.db.admin_users.find_one({"_id": ObjectId(current_admin.id)})
        
        if not admin_data:
            logger.error(f"Admin with ID {current_admin.id} not found in database")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Admin user not found"
            )

        vector_store_id = admin_data.get("vector_store_id")

        if not vector_store_id:
            try:
                # Create a new vector store
                logger.info(f"Creating new vector store with name: {vs_name} and file ID: {openai_file['id']}")
                vector_store = await openai_service.create_vector_store(
                    name=vs_name,
                    file_ids=[openai_file["id"]]
                )
                
                if not vector_store:
                    logger.error("Vector store creation returned None")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Failed to create vector store: received null response"
                    )
                    
                if "id" not in vector_store:
                    logger.error(f"Vector store response missing 'id' field: {vector_store}")
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Vector store creation response missing 'id' field"
                    )
                    
                vector_store_id = vector_store["id"]
                logger.info(f"Created new vector store with ID: {vector_store_id}")
                
            except Exception as vs_error:
                logger.error(f"Error creating vector store: {str(vs_error)}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to create vector store: {str(vs_error)}"
                )
            
            # Save vector store ID to admin record
            await db.db.admin_users.update_one(
                {"_id": current_admin.id},
                {"$set": {"vector_store_id": vector_store_id}}
            )
            
            # Attach vector store to assistant
            await openai_service.attach_vector_store_to_assistant(
                assistant_id=current_admin.assistant_id,
                vector_store_id=vector_store_id
            )
        else:
            # Add file to existing vector store
            await openai_service.add_file_to_vector_store(
                vector_store_id=vector_store_id,
                file_id=openai_file["id"]
            )
        
        # Store file information in MongoDB
        file_record = {
            "admin_id": str(current_admin.id),
            "filename": file.filename,
            "openai_file_id": openai_file["id"],
            "vector_store_id": vector_store_id,
            "size": file_size,
            "upload_date": openai_file.get("created_at", datetime.utcnow())
        }
        
        await db.db.admin_files.insert_one(file_record)
        
        return {
            "status": "success",
            "message": f"File {file.filename} uploaded successfully",
            "file_id": openai_file["id"],
            "vector_store_id": vector_store_id
        }
        
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload file: {str(e)}"
        )