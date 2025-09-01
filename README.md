# Sensing Garden Livestream - show & tell

*This branch is dedicated to show the stream from the sensing garden pipeline running to collect data on insect activity and count on a local webpage.*

## Hardware setup
### 1. [Connect the camera module to your raspberrypi5](documentation/raspberrypi_setup.md)
### 2. [Connect the active cooler and AI HAT](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html)(external website)

## Installation

### 1. Clone repo
```bash
git clone https://github.com/aasehaa/sensing-garden.git
```
...make sure to move into the correct branch. 
### 2. Install Hailo to run inferrence
**Requirements**
- numpy < 2.0.0
- setproctitle
- opencv-python
```bash
sudo apt install hailo-all
```
### 3. Run script to automate installation process
```bash
./install.sh
```
### 4. Source environment 
```bash
source setup_env.sh
```
### 5. Prepare new classification model
*Expects to you already have a HEF model ready to run on the HAILO AI HAT*

When running a new classification model with this script, you need to make sure to have the correct taxonomic data added to your scripts. 

Build the taxonomic json file from txt file with species names:
species.txt example: 
```txt 
Chrysoteuchia culmella
Choristoneura fumiferana
Hypoprepia fucosa
...
```
Get taxonomy from GBIF for hierarchical classification from gbif (remember to have correct file path to txt file). This will generate a json file `species.json` you would need to run the classification model: 
```bash
python get_taxonomy_gbif.py --species-list species_list.txt
```


Change number of family, genus and species in script, depending on your classification model and taxonomy restuls from the previous step: 
```python
def process_classification_results(self, classification_results, detection_data):
            class_names = self.class_names
            nr_genus = 33 # TODO edit
            nr_family = 9 # TODO edit
            nr_species = 36 # TODO edit
...
```

### 6. Edit html with yout server IP
Replace with your Pis IP in the `viewer.html` file: 
```html
    const ws = new WebSocket("ws://[add IP adress]:8765"); // TODO edit wlan0 (ifconfig)
```

### 7. Run script

To run a full detection example, you need to specify the HEF model you want to run:
```bash
python moth/run_moth.py --hef-path resources/classification-model.hef
```
### 8. Setup http server (locally)

To run the server locally, simply type this in a new terminal window: 
```bash
python -m http.server 8080
```

Visit local webpage with your server IP: 

`http://[add IP adress]:8080/viewer.html`


