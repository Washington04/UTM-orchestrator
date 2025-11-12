# utm-airspace-generator
A UTM simulator that will define a geographical area (Seattle Metro), generate operational intents, then deconflict those intents. This project should comply with as may governing regulations as possible, ie ASTM F3548, PART108, AC146-1, U-space guidance, etc. This project should mimic an ADSP / UAS Service Supplier. 

Goals: 
- establish Seattle Metro area of responsibility
- randomly generate area-based and vector-based operational intents
- deconflict based on prioritization level

-----

The Seattle Metro area polygon is bounded by the following points:
pt 1: 47N, -122.5W
pt 2: 48N, -122.5W
pt 3: 48N, -121.5W
pt 4: 47N, -121.5W
return to pt of origin
