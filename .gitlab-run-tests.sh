apt -y update
echo ---- ---- ---- BUILD IMAGE ---- ---- ----

pip3 install -r requirements.txt
pip3 install -r requirements_opengroup.txt
pip3 install -r requirements_dev.txt

echo ---- ---- ---- UNIT TESTS ---- ---- ----
echo ---- ---- AZURITE SETUP
apt -y install nodejs npm
npm install azurite
mkdir azurite
./node_modules/azurite/dist/src/azurite.js --silent --location azurite --debug azurite/debug.log &
sleep 1
pytest tests --junitxml=report.xml