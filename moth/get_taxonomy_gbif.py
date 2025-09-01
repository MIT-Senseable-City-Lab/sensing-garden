import requests
import argparse
import json



def load_class_names(class_names_path):
    with open(class_names_path, 'r') as f:
        class_names = [line.strip() for line in f.readlines()]
    print(f"Loaded {len(class_names)} class names")
    return class_names

def get_taxonomy_from_gbif(species_list):
        taxonomy = {"1": [], "2": {}, "3": {}}
        print(f"\nBuilding taxonomy for {len(species_list)} species from GBIF...")
        for species_name in species_list:
            url = f"https://api.gbif.org/v1/species/match?name={species_name}&verbose=true"
            response = requests.get(url)
            data = response.json()
            if data.get('status') in ['ACCEPTED', 'SYNONYM', 'DOUBTFUL']:
                family, genus = data.get('family'), data.get('genus')
                if family and genus:
                    if family not in taxonomy["1"]: taxonomy["1"].append(family)
                    taxonomy["2"][genus] = family
                    taxonomy["3"][species_name] = genus
                else: 
                    taxonomy["2"][genus] = "None" # defaulting to none
                    taxonomy["3"][species_name] = "None" # defaulting to none
                    #raise RuntimeError(f"{species_name} - missing family/genus data")
                
            else: raise RuntimeError(f"{species_name} not found in GBIF")
        taxonomy["1"] = sorted(list(set(taxonomy["1"])))

        with open('species.json', 'w') as json_file:
            json.dump(taxonomy, json_file)
        return taxonomy

def build_taxonomy(class_names):
    if not class_names:
        return [], [], {}, {}
    taxonomy = get_taxonomy_from_gbif(class_names)
    families = taxonomy["1"]
    genus_to_family = taxonomy["2"]
    species_to_genus = taxonomy["3"]
    genera = list(genus_to_family.keys())
    print(f"Built taxonomy: {len(families)} families, {len(genera)} genera")
    return families, genera, genus_to_family, species_to_genus


def main():
    parser = argparse.ArgumentParser(description='Continuous video recording and inference pipeline.')
    parser.add_argument('--species-list', type=str, default='species', help='Path to txt file of species.')

    args = parser.parse_args()

    try: 
        species_list = args.species_list
    except ValueError:
        print(f"Error: Invalid file path '{args.species_list}'")
        return 1
    

    class_names = load_class_names(species_list)
    families, genera, genus_to_family, species_to_genus = build_taxonomy(class_names)
    print("taxonomy initialized successfully ans daved to species.json")
    
    return 0


if __name__ == "__main__":
    exit(main())

