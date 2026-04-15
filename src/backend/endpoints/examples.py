import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/examples", tags=["examples"])

# All example files live under this directory.
# Add new subfolders (e.g. examples/banaan/, examples/roster/) at any time
# without touching the endpoint code.
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


class ExampleFile(BaseModel):
    name: str
    filename: str


@router.get("/{module}", response_model=list[ExampleFile])
def list_examples(module: str) -> list[ExampleFile]:
    """Return all available example files for a specific module (subfolder name)."""
    module_dir = EXAMPLES_DIR / module
    if not module_dir.is_dir():
        return []

    results: list[ExampleFile] = []
    for file in sorted(module_dir.iterdir()):
        if file.is_file() and not file.name.startswith("."):
            results.append(ExampleFile(
                name=file.stem.replace("_", " ").title(),
                filename=file.name,
            ))
    return results


@router.get("/{module}/{filename}")
def download_example(module: str, filename: str) -> FileResponse:
    """Download a specific example file.

    - **module**: subfolder name (e.g. `banaan`, `roster`)
    - **filename**: exact filename including extension (e.g. `example_students.csv`)
    """
    # Prevent directory traversal
    if "/" in module or "\\" in module or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid path component")

    file_path = (EXAMPLES_DIR / module / filename).resolve()

    # Ensure the resolved path stays within EXAMPLES_DIR
    try:
        file_path.relative_to(EXAMPLES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Example '{module}/{filename}' not found")

    media_type, _ = mimetypes.guess_type(filename)
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type or "application/octet-stream",
    )
