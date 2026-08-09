"""PDF Service - Parse PDFs, extract text, index in database, duplicate detection."""

import hashlib
import logging

from sqlalchemy import select, and_

from database import async_session
from models import PDFIndex
from services.moderation import compute_file_hash, is_duplicate_file, add_audit_log

log = logging.getLogger(__name__)


def extract_text_from_pdf(file_content: bytes) -> str:
    """Extract text from a PDF file's bytes."""
    try:
        from io import BytesIO
        from PyPDF2 import PdfReader
        reader = PdfReader(BytesIO(file_content))
        text = ""
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + "\n"
        return text.strip()
    except Exception as e:
        log.error("PDF parse error: %s", e)
        return ""


async def index_pdf(
    file_id: str, file_name: str, file_content: bytes,
    uploaded_by: int, subject: str | None = None,
    chapter: str | None = None, keywords: list[str] | None = None,
    teacher_name: str | None = None,
) -> dict:
    """Index a PDF in the database. Returns {status, message, pdf_id}."""
    import json

    file_hash = await compute_file_hash(file_content)

    # Check duplicate
    if await is_duplicate_file(file_hash):
        return {"status": "duplicate", "message": "⚠️ Yeh file pehle se channel mein available hai!", "pdf_id": None}

    async with async_session() as session:
        pdf = PDFIndex(
            file_id=file_id,
            file_name=file_name,
            subject=subject,
            chapter=chapter,
            keywords=json.dumps(keywords or []),
            uploaded_by=uploaded_by,
            is_approved=False,  # Needs admin approval
            file_hash=file_hash,
            teacher_name=teacher_name,
        )
        session.add(pdf)
        await session.commit()
        await session.refresh(pdf)

        await add_audit_log(
            admin_id=None, target_user_id=uploaded_by,
            action_type="pdf_upload",
            reason=f"Uploaded: {file_name}",
            details={"pdf_id": pdf.pdf_id, "file_hash": file_hash},
        )

    return {
        "status": "pending_approval",
        "message": f"📥 PDF '{file_name}' save ho gaya. Admin approval ke baad channel par publish hoga.",
        "pdf_id": pdf.pdf_id,
    }


async def approve_pdf(pdf_id: int, channel_message_id: int | None = None, keywords: list[str] | None = None) -> bool:
    """Approve a pending PDF."""
    import json
    async with async_session() as session:
        pdf = await session.get(PDFIndex, pdf_id)
        if not pdf:
            return False
        pdf.is_approved = True
        if channel_message_id:
            pdf.channel_message_id = channel_message_id
        if keywords:
            pdf.keywords = json.dumps(keywords)
        await session.commit()
    return True


async def reject_pdf(pdf_id: int) -> bool:
    """Reject and remove a pending PDF."""
    async with async_session() as session:
        pdf = await session.get(PDFIndex, pdf_id)
        if not pdf:
            return False
        await session.delete(pdf)
        await session.commit()
    return True


async def get_pending_pdfs() -> list[PDFIndex]:
    """Get PDFs waiting for admin approval."""
    async with async_session() as session:
        result = await session.execute(
            select(PDFIndex).where(PDFIndex.is_approved == False)
            .order_by(PDFIndex.timestamp.desc())
        )
        return list(result.scalars().all())


async def search_pdfs(subject: str | None = None, keyword: str | None = None) -> list[PDFIndex]:
    """Search approved PDFs by subject or keyword."""
    async with async_session() as session:
        query = select(PDFIndex).where(PDFIndex.is_approved == True)
        if subject:
            query = query.where(PDFIndex.subject == subject)
        if keyword:
            query = query.where(PDFIndex.keywords.contains(keyword.lower()))
        result = await session.execute(query)
        return list(result.scalars().all())
