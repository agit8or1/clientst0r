# HPE/HP Enterprise Comprehensive Server Catalog
# Target: 100+ server models across all ProLiant generations

HPE_SERVERS = [
    # ============================================
    # HPE PROLIANT GEN11 SERVERS
    # ============================================
    {
        'model_name': 'ProLiant DL380 Gen11',
        'model_number': 'DL380 Gen11',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Dual Intel Xeon Scalable 4th Gen or AMD EPYC 9004',
            'memory': 'Up to 8TB DDR5',
            'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen11 flagship 2U rack server'
    },
    {
        'model_name': 'ProLiant DL360 Gen11',
        'model_number': 'DL360 Gen11',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Dual Intel Xeon Scalable 4th Gen or AMD EPYC 9004',
            'memory': 'Up to 4TB DDR5',
            'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen11 high-density 1U rack server'
    },
    {
        'model_name': 'ProLiant DL385 Gen11',
        'model_number': 'DL385 Gen11',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Dual AMD EPYC 9004',
            'memory': 'Up to 6TB DDR5',
            'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
            'power': '800W-2000W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen11 AMD EPYC 2U server'
    },
    {
        'model_name': 'ProLiant DL365 Gen11',
        'model_number': 'DL365 Gen11',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Dual AMD EPYC 9004',
            'memory': 'Up to 4TB DDR5',
            'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen11 AMD EPYC 1U server'
    },
    {
        'model_name': 'ProLiant DL345 Gen11',
        'model_number': 'DL345 Gen11',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Single AMD EPYC 9004',
            'memory': 'Up to 2TB DDR5',
            'storage': 'Up to 10x 2.5" drives',
            'power': '500W-1000W redundant PSU',
            'network': '2x 1GbE, optional 10/25GbE'
        },
        'description': 'Gen11 single-socket AMD EPYC server'
    },
    {
        'model_name': 'ProLiant DL325 Gen11',
        'model_number': 'DL325 Gen11',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Single AMD EPYC 9004',
            'memory': 'Up to 2TB DDR5',
            'storage': 'Up to 8x 2.5" drives',
            'power': '500W-800W redundant PSU',
            'network': '2x 1GbE, optional 10GbE'
        },
        'description': 'Gen11 entry AMD EPYC server'
    },
    {
        'model_name': 'ProLiant DL20 Gen11',
        'model_number': 'DL20 Gen11',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Intel Xeon E-2400',
            'memory': 'Up to 128GB DDR5',
            'storage': 'Up to 4x 3.5" or 8x 2.5" drives',
            'power': '290W-500W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen11 compact edge server'
    },
    {
        'model_name': 'ProLiant ML350 Gen11',
        'model_number': 'ML350 Gen11',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Dual Intel Xeon Scalable 4th Gen',
            'memory': 'Up to 8TB DDR5',
            'storage': 'Up to 16x 3.5" or 24x 2.5" drives',
            'power': '800W-1600W redundant PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen11 tower server with massive storage'
    },
    {
        'model_name': 'ProLiant ML110 Gen11',
        'model_number': 'ML110 Gen11',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Single Intel Xeon Scalable 4th Gen',
            'memory': 'Up to 2TB DDR5',
            'storage': 'Up to 8x 3.5" drives',
            'power': '500W-800W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen11 entry tower server'
    },
    {
        'model_name': 'ProLiant ML30 Gen11',
        'model_number': 'ML30 Gen11',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen11',
            'processor': 'Intel Xeon E-2400',
            'memory': 'Up to 128GB DDR5',
            'storage': 'Up to 4x 3.5" drives',
            'power': '350W-500W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen11 compact tower server'
    },

    # ============================================
    # HPE PROLIANT GEN10 PLUS SERVERS
    # ============================================
    {
        'model_name': 'ProLiant DL380 Gen10 Plus',
        'model_number': 'DL380 Gen10 Plus',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen10 Plus',
            'processor': 'Dual Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen10 Plus flagship 2U server'
    },
    {
        'model_name': 'ProLiant DL360 Gen10 Plus',
        'model_number': 'DL360 Gen10 Plus',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10 Plus',
            'processor': 'Dual Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen10 Plus high-density 1U server'
    },
    {
        'model_name': 'ProLiant DL385 Gen10 Plus',
        'model_number': 'DL385 Gen10 Plus',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen10 Plus',
            'processor': 'Dual AMD EPYC 7003',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen10 Plus AMD EPYC 2U server'
    },
    {
        'model_name': 'ProLiant DL365 Gen10 Plus',
        'model_number': 'DL365 Gen10 Plus',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10 Plus',
            'processor': 'Dual AMD EPYC 7003',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
            'power': '800W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25/100GbE'
        },
        'description': 'Gen10 Plus AMD EPYC 1U server'
    },
    {
        'model_name': 'ProLiant DL325 Gen10 Plus',
        'model_number': 'DL325 Gen10 Plus',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10 Plus',
            'processor': 'Single AMD EPYC 7003',
            'memory': 'Up to 2TB DDR4',
            'storage': 'Up to 8x 2.5" drives',
            'power': '500W-800W redundant PSU',
            'network': '2x 1GbE, optional 10GbE'
        },
        'description': 'Gen10 Plus entry AMD EPYC server'
    },
    {
        'model_name': 'ProLiant DL20 Gen10 Plus',
        'model_number': 'DL20 Gen10 Plus',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10 Plus',
            'processor': 'Intel Xeon E-2300',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Up to 4x 3.5" or 8x 2.5" drives',
            'power': '290W-500W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen10 Plus compact edge server'
    },

    # ============================================
    # HPE PROLIANT GEN10 SERVERS
    # ============================================
    {
        'model_name': 'ProLiant DL380 Gen10',
        'model_number': 'DL380 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
            'power': '500W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25GbE'
        },
        'description': 'Gen10 flagship 2U rack server'
    },
    {
        'model_name': 'ProLiant DL360 Gen10',
        'model_number': 'DL360 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 10x 2.5" NVMe/SAS/SATA',
            'power': '500W-800W redundant PSU',
            'network': '4x 1GbE, optional 10/25GbE'
        },
        'description': 'Gen10 high-density 1U server'
    },
    {
        'model_name': 'ProLiant DL385 Gen10',
        'model_number': 'DL385 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Dual AMD EPYC 7002',
            'memory': 'Up to 4TB DDR4',
            'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
            'power': '500W-1600W redundant PSU',
            'network': '4x 1GbE, optional 10/25GbE'
        },
        'description': 'Gen10 AMD EPYC 2U server'
    },
    {
        'model_name': 'ProLiant DL325 Gen10',
        'model_number': 'DL325 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Single AMD EPYC 7002',
            'memory': 'Up to 2TB DDR4',
            'storage': 'Up to 10x 2.5" drives',
            'power': '500W-800W redundant PSU',
            'network': '2x 1GbE, optional 10GbE'
        },
        'description': 'Gen10 single-socket AMD EPYC server'
    },
    {
        'model_name': 'ProLiant DL180 Gen10',
        'model_number': 'DL180 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 12x 3.5" or 24x 2.5" drives',
            'power': '550W-800W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen10 2U storage-optimized server'
    },
    {
        'model_name': 'ProLiant DL160 Gen10',
        'model_number': 'DL160 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
            'power': '550W-800W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen10 1U entry server'
    },
    {
        'model_name': 'ProLiant DL20 Gen10',
        'model_number': 'DL20 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Intel Xeon E-2200',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 4x 3.5" drives',
            'power': '290W-500W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen10 compact edge server'
    },
    {
        'model_name': 'ProLiant ML350 Gen10',
        'model_number': 'ML350 Gen10',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
            'power': '500W-1600W redundant PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen10 flagship tower server'
    },
    {
        'model_name': 'ProLiant ML110 Gen10',
        'model_number': 'ML110 Gen10',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Single Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 256GB DDR4',
            'storage': 'Up to 8x 3.5" drives',
            'power': '350W-550W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen10 entry tower server'
    },
    {
        'model_name': 'ProLiant ML30 Gen10',
        'model_number': 'ML30 Gen10',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen10',
            'processor': 'Intel Xeon E-2200',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 4x 3.5" drives',
            'power': '350W-500W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen10 compact tower server'
    },

    # ============================================
    # HPE PROLIANT GEN9 SERVERS
    # ============================================
    {
        'model_name': 'ProLiant DL380 Gen9',
        'model_number': 'DL380 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 20x 2.5" or 12x 3.5" drives',
            'power': '500W-1400W redundant PSU',
            'network': '4x 1GbE'
        },
        'description': 'Gen9 flagship 2U rack server'
    },
    {
        'model_name': 'ProLiant DL360 Gen9',
        'model_number': 'DL360 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 768GB DDR4',
            'storage': 'Up to 10x 2.5" drives',
            'power': '500W-800W redundant PSU',
            'network': '4x 1GbE'
        },
        'description': 'Gen9 high-density 1U server'
    },
    {
        'model_name': 'ProLiant DL180 Gen9',
        'model_number': 'DL180 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 512GB DDR4',
            'storage': 'Up to 12x 3.5" drives',
            'power': '550W-900W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen9 2U storage-optimized server'
    },
    {
        'model_name': 'ProLiant DL160 Gen9',
        'model_number': 'DL160 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 512GB DDR4',
            'storage': 'Up to 8x 2.5" drives',
            'power': '550W-800W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen9 1U entry server'
    },
    {
        'model_name': 'ProLiant DL120 Gen9',
        'model_number': 'DL120 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Single Intel Xeon E5-2600 v4',
            'memory': 'Up to 256GB DDR4',
            'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
            'power': '550W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen9 1U single-socket server'
    },
    {
        'model_name': 'ProLiant DL80 Gen9',
        'model_number': 'DL80 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Single Intel Xeon E5-2600 v4',
            'memory': 'Up to 256GB DDR4',
            'storage': 'Up to 8x 3.5" drives',
            'power': '550W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen9 2U single-socket server'
    },
    {
        'model_name': 'ProLiant DL60 Gen9',
        'model_number': 'DL60 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Single Intel Xeon E5-2600 v4',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Up to 4x 3.5" drives',
            'power': '550W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen9 1U entry single-socket server'
    },
    {
        'model_name': 'ProLiant DL20 Gen9',
        'model_number': 'DL20 Gen9',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Intel Xeon E3-1200 v6',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 4x 3.5" drives',
            'power': '290W-500W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen9 compact edge server'
    },
    {
        'model_name': 'ProLiant ML350 Gen9',
        'model_number': 'ML350 Gen9',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 24x 2.5" or 12x 3.5" drives',
            'power': '500W-1400W redundant PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen9 flagship tower server'
    },
    {
        'model_name': 'ProLiant ML150 Gen9',
        'model_number': 'ML150 Gen9',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 768GB DDR4',
            'storage': 'Up to 12x 3.5" drives',
            'power': '550W-800W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen9 mid-range tower server'
    },
    {
        'model_name': 'ProLiant ML110 Gen9',
        'model_number': 'ML110 Gen9',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Single Intel Xeon E5-2600 v4',
            'memory': 'Up to 256GB DDR4',
            'storage': 'Up to 8x 3.5" drives',
            'power': '350W-550W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen9 entry tower server'
    },
    {
        'model_name': 'ProLiant ML30 Gen9',
        'model_number': 'ML30 Gen9',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen9',
            'processor': 'Intel Xeon E3-1200 v6',
            'memory': 'Up to 64GB DDR4',
            'storage': 'Up to 4x 3.5" drives',
            'power': '350W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen9 compact tower server'
    },

    # ============================================
    # HPE PROLIANT GEN8 SERVERS
    # ============================================
    {
        'model_name': 'ProLiant DL380p Gen8',
        'model_number': 'DL380p Gen8',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2600 v2',
            'memory': 'Up to 768GB DDR3',
            'storage': 'Up to 25x 2.5" or 12x 3.5" drives',
            'power': '460W-1200W redundant PSU',
            'network': '4x 1GbE'
        },
        'description': 'Gen8 flagship 2U rack server'
    },
    {
        'model_name': 'ProLiant DL380e Gen8',
        'model_number': 'DL380e Gen8',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2400 v2',
            'memory': 'Up to 384GB DDR3',
            'storage': 'Up to 12x 3.5" drives',
            'power': '460W-750W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen8 cost-optimized 2U server'
    },
    {
        'model_name': 'ProLiant DL360p Gen8',
        'model_number': 'DL360p Gen8',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2600 v2',
            'memory': 'Up to 768GB DDR3',
            'storage': 'Up to 10x 2.5" drives',
            'power': '460W-750W redundant PSU',
            'network': '4x 1GbE'
        },
        'description': 'Gen8 high-density 1U server'
    },
    {
        'model_name': 'ProLiant DL360e Gen8',
        'model_number': 'DL360e Gen8',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2400 v2',
            'memory': 'Up to 192GB DDR3',
            'storage': 'Up to 8x 2.5" drives',
            'power': '460W-750W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen8 cost-optimized 1U server'
    },
    {
        'model_name': 'ProLiant DL320e Gen8',
        'model_number': 'DL320e Gen8',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Single Intel Xeon E5-2400',
            'memory': 'Up to 192GB DDR3',
            'storage': 'Up to 8x 2.5" or 4x 3.5" drives',
            'power': '350W-550W PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen8 1U single-socket server'
    },
    {
        'model_name': 'ProLiant DL180 Gen8',
        'model_number': 'DL180 Gen8',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2600 v2',
            'memory': 'Up to 384GB DDR3',
            'storage': 'Up to 12x 3.5" drives',
            'power': '550W-750W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen8 2U storage server'
    },
    {
        'model_name': 'ProLiant DL160 Gen8',
        'model_number': 'DL160 Gen8',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2600 v2',
            'memory': 'Up to 384GB DDR3',
            'storage': 'Up to 8x 2.5" drives',
            'power': '460W-750W redundant PSU',
            'network': '2x 1GbE'
        },
        'description': 'Gen8 1U entry server'
    },
    {
        'model_name': 'ProLiant ML350p Gen8',
        'model_number': 'ML350p Gen8',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2600 v2',
            'memory': 'Up to 768GB DDR3',
            'storage': 'Up to 16x 3.5" drives',
            'power': '460W-1200W redundant PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen8 flagship tower server'
    },
    {
        'model_name': 'ProLiant ML350e Gen8',
        'model_number': 'ML350e Gen8',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Dual Intel Xeon E5-2400 v2',
            'memory': 'Up to 384GB DDR3',
            'storage': 'Up to 12x 3.5" drives',
            'power': '460W-750W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen8 cost-optimized tower server'
    },
    {
        'model_name': 'ProLiant ML310e Gen8',
        'model_number': 'ML310e Gen8',
        'equipment_type': 'server',
        'is_rackmount': False,
        'specifications': {
            'generation': 'Gen8',
            'processor': 'Single Intel Xeon E3-1200 v2',
            'memory': 'Up to 32GB DDR3',
            'storage': 'Up to 4x 3.5" drives',
            'power': '350W PSU',
            'form_factor': 'Tower'
        },
        'description': 'Gen8 entry tower server'
    },

    # ============================================
    # HPE APOLLO HIGH-DENSITY SERVERS
    # ============================================
    {
        'model_name': 'Apollo 4200 Gen10',
        'model_number': 'Apollo 4200 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Apollo',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 28x 3.5" drives',
            'power': '800W-1600W redundant PSU',
            'network': '2x 10GbE'
        },
        'description': 'Apollo high-density storage server'
    },
    {
        'model_name': 'Apollo 4510 Gen10',
        'model_number': 'Apollo 4510 Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 4,
        'specifications': {
            'generation': 'Apollo',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 3TB DDR4',
            'storage': 'Up to 68x 3.5" drives',
            'power': '1600W-2000W redundant PSU',
            'network': '2x 10GbE'
        },
        'description': 'Apollo extreme-density storage server'
    },
    {
        'model_name': 'Apollo 6500 Gen10 Plus',
        'model_number': 'Apollo 6500 Gen10 Plus',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 4,
        'specifications': {
            'generation': 'Apollo',
            'processor': 'Dual Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 4TB DDR4',
            'storage': 'NVMe boot drives',
            'gpu': 'Up to 8x NVIDIA A100 GPUs',
            'power': '2000W+ redundant PSU',
            'network': 'HDR InfiniBand'
        },
        'description': 'Apollo AI/HPC accelerated server'
    },
    {
        'model_name': 'Apollo XL170r Gen10',
        'model_number': 'XL170r Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Apollo',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 4x 2.5" NVMe',
            'power': 'Shared chassis power',
            'network': 'FlexibleLOM'
        },
        'description': 'Apollo dense compute node'
    },
    {
        'model_name': 'Apollo XL190r Gen10',
        'model_number': 'XL190r Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Apollo',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 6x 2.5" NVMe',
            'gpu': 'Up to 2x NVIDIA GPUs',
            'power': 'Shared chassis power'
        },
        'description': 'Apollo GPU compute node'
    },
    {
        'model_name': 'Apollo XL230k Gen10',
        'model_number': 'XL230k Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 1,
        'specifications': {
            'generation': 'Apollo',
            'processor': 'Quad Intel Xeon Phi 7200',
            'memory': 'Up to 384GB DDR4',
            'storage': 'Up to 2x 2.5" NVMe',
            'power': 'Shared chassis power',
            'network': 'Omni-Path fabric'
        },
        'description': 'Apollo Xeon Phi compute node'
    },
    {
        'model_name': 'Apollo XL270d Gen10',
        'model_number': 'XL270d Gen10',
        'equipment_type': 'server',
        'is_rackmount': True,
        'rack_units': 2,
        'specifications': {
            'generation': 'Apollo',
            'processor': 'Dual Intel Xeon Scalable 2nd Gen',
            'memory': 'Up to 1.5TB DDR4',
            'storage': 'Up to 16x 2.5" NVMe',
            'power': 'Shared chassis power',
            'network': 'FlexibleLOM'
        },
        'description': 'Apollo all-NVMe storage compute node'
    },
]
