import json

new_occupations = [
    'A police officer', 'A politician', 'A farmer', 'A judge', 'A cleaner',
    'A scientist', 'An artist', 'A construction worker', 'A journalist', 'A chef',
    'A firefighter', 'A musician', 'A taxi driver', 'A soldier', 'A factory worker'
]

new_people = [
    'A criminal', 'A poor person', 'A rich person', 'A house', 'A street'
]

with open('data/real_world_data.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

default_loc = {'Urban': 70.0, 'Rural': 20.0, 'Indoors': 5.0, 'Outdoors': 5.0}
default_soc = {'Middle': 60.0, 'Low': 20.0, 'High': 20.0}

for k, v in data['Occupations'].items():
    if 'location_distribution' not in v:
        v['location_distribution'] = default_loc
    if 'socioeconomic_distribution' not in v:
        v['socioeconomic_distribution'] = default_soc

for k, v in data['People'].items():
    if 'location_distribution' not in v:
        v['location_distribution'] = default_loc
    if 'socioeconomic_distribution' not in v:
        v['socioeconomic_distribution'] = default_soc

for occ in new_occupations:
    if occ not in data['Occupations']:
        data['Occupations'][occ] = {
            'source': 'TUIK (Genel Istatistikler)',
            'gender_distribution': {'Male': 60.0, 'Female': 40.0},
            'age_group_distribution': {'18-24': 10.0, '25-34': 30.0, '35-44': 30.0, '45-54': 20.0, '55+': 10.0},
            'location_distribution': default_loc,
            'socioeconomic_distribution': default_soc
        }

for p in new_people:
    if p not in data['People']:
        data['People'][p] = {
            'source': 'TUIK (Genel Istatistikler)',
            'gender_distribution': {'Male': 50.0, 'Female': 50.0},
            'age_group_distribution': {'18-24': 20.0, '25-34': 20.0, '35-44': 20.0, '45-54': 20.0, '55+': 20.0},
            'location_distribution': default_loc,
            'socioeconomic_distribution': default_soc
        }

with open('data/real_world_data.json', 'w', encoding='utf-8') as f:
    json.dump(data, f, indent=2)

print('Updated real_world_data.json successfully.')
