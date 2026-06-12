$ErrorActionPreference = "Stop"

$env:JAVA_HOME = "D:\Multi-Agentic-RAG\neo4j\desktop-data\Application\Cache\runtime\zulu21.48.17-ca-jre21.0.10-win_x64"
$env:PATH = "D:\Multi-Agentic-RAG\neo4j\desktop-data\Application\Cache\runtime\zulu21.48.17-ca-jre21.0.10-win_x64\bin;$env:PATH"

Set-Location "D:\Multi-Agentic-RAG\neo4j\desktop-data\Application\Data\dbmss\dbms-df0e53a4-7e80-4109-8a5e-a485400d9541"

"$(Get-Date -Format o) Starting Neo4j console..." | Out-File -FilePath "D:\Multi-Agentic-RAG\neo4j\runtime\neo4j-console-runner.log" -Append -Encoding utf8
& "D:\Multi-Agentic-RAG\neo4j\desktop-data\Application\Data\dbmss\dbms-df0e53a4-7e80-4109-8a5e-a485400d9541\bin\neo4j.bat" console *>> "D:\Multi-Agentic-RAG\neo4j\runtime\neo4j-console-runner.log"
"$(Get-Date -Format o) Neo4j console stopped." | Out-File -FilePath "D:\Multi-Agentic-RAG\neo4j\runtime\neo4j-console-runner.log" -Append -Encoding utf8
