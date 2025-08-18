import os
import subprocess
import logging
import logging.handlers
import json
from mcp.server.fastmcp import FastMCP

# -------------------------------
# Logging Setup
# -------------------------------
LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

class JsonFormatter(logging.Formatter):
    """Custom JSON log formatter"""
    def format(self, record):
        log_record = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno
        }
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)

logger = logging.getLogger("terminal_server")
logger.setLevel(logging.INFO)

# Rotating file handler (5 MB per file, keep 5 backups)
file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(LOG_DIR, "server.log"),
    maxBytes=5 * 1024 * 1024,
    backupCount=5
)
file_handler.setFormatter(JsonFormatter())

# Console handler (pretty logs while developing)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# -------------------------------
# MCP Server Setup
# -------------------------------
mcp = FastMCP("Terminal")
DEFAULT_WORKSPACE = os.path.expanduser(
    "/run/media/reyandabreo/Projects/MCP/MCP_Client_Server_Testing/workspace"
)

@mcp.tool()
async def run_command(command: str) -> str:
    """
    Run a terminal command inside the workspace directory.
    Logs all commands and outputs in structured JSON.
    """
    logger.info(f"Received command: {command}")

    try:
        result = subprocess.run(
            command, 
            shell=True, 
            cwd=DEFAULT_WORKSPACE, 
            capture_output=True, 
            text=True
        )
        
        output = result.stdout or result.stderr
        logger.info(
            f"Command executed",
            extra={"command": command, "exit_code": result.returncode, "output": output[:200]}  # truncate output
        )

        return output
    except Exception as e:
        logger.error("Error running command", exc_info=True, extra={"command": command})
        return str(e)

if __name__ == "__main__":
    logger.info("🚀 Terminal MCP server starting...")
    mcp.run(transport='stdio')
    logger.info("🛑 Terminal MCP server stopped.")
