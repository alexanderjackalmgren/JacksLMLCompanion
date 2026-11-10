#install dependencies (create file if not present based on project)
pip install -r requirements.txt

#Running the Application
python src/app.py

#Compiling to a Standalone Executable (.exe)
#To package the app for non-technical users so they do not need Python installed:

    pip install pyinstaller

#Build the standalone executable:

    pyinstaller --noconsole --onefile --name "JacksLMLCompanion" src/app.py

#The compiled binary will be generated in the dist/ folder as JacksLMLCompanion.exe.

---

### `requirements.txt`
```text
PyQt6>=6.4.0
rarfile>=4.0
requests>=2.28.0

