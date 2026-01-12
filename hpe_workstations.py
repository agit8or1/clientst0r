# HPE/HP Workstations - Z-Series, EliteDesk, ProDesk
# Target: 50+ workstation models

HPE_WORKSTATIONS = [
    # ============================================
    # HP Z WORKSTATIONS - FLAGSHIP
    # ============================================
    {
        'model_name': 'Z8 G5',
        'model_number': 'Z8 G5',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon W or Xeon Scalable 4th Gen',
            'memory': 'Up to 2TB DDR5',
            'storage': 'Up to 12x M.2 NVMe + SATA',
            'graphics': 'Up to 3x NVIDIA RTX 6000 Ada',
            'form_factor': 'Tower'
        },
        'description': 'Flagship dual-socket workstation'
    },
    {
        'model_name': 'Z8 G4',
        'model_number': 'Z8 G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon Scalable 3rd Gen',
            'memory': 'Up to 2TB DDR4',
            'storage': 'Up to 10x M.2 NVMe + SATA',
            'graphics': 'Up to 3x NVIDIA RTX A6000',
            'form_factor': 'Tower'
        },
        'description': 'Flagship dual-socket workstation'
    },
    {
        'model_name': 'Z6 G5',
        'model_number': 'Z6 G5',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Single Intel Xeon W 3400 or 2400',
            'memory': 'Up to 512GB DDR5',
            'storage': 'Up to 8x M.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA RTX 6000 Ada',
            'form_factor': 'Tower'
        },
        'description': 'High-performance single-socket workstation'
    },
    {
        'model_name': 'Z6 G4',
        'model_number': 'Z6 G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Single Intel Xeon W-3300',
            'memory': 'Up to 512GB DDR4',
            'storage': 'Up to 6x M.2 NVMe + SATA',
            'graphics': 'Up to 2x NVIDIA RTX A6000',
            'form_factor': 'Tower'
        },
        'description': 'High-performance single-socket workstation'
    },
    {
        'model_name': 'Z4 G5',
        'model_number': 'Z4 G5',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon W-2400 or Core i9 13th Gen',
            'memory': 'Up to 512GB DDR5',
            'storage': 'Up to 6x M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX 6000 Ada',
            'form_factor': 'Tower'
        },
        'description': 'Entry professional workstation'
    },
    {
        'model_name': 'Z4 G4',
        'model_number': 'Z4 G4',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon W-1200/2200 or Core i9 10th Gen',
            'memory': 'Up to 256GB DDR4',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A6000',
            'form_factor': 'Tower'
        },
        'description': 'Entry professional workstation'
    },
    {
        'model_name': 'Z2 G9 Tower',
        'model_number': 'Z2 G9 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen or Xeon W',
            'memory': 'Up to 128GB DDR5',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A5500',
            'form_factor': 'Tower'
        },
        'description': 'Mainstream workstation tower'
    },
    {
        'model_name': 'Z2 G9 SFF',
        'model_number': 'Z2 G9 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen or Xeon W',
            'memory': 'Up to 128GB DDR5',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A4000',
            'form_factor': 'Small Form Factor'
        },
        'description': 'Compact workstation SFF'
    },
    {
        'model_name': 'Z2 G8 Tower',
        'model_number': 'Z2 G8 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen or Xeon W',
            'memory': 'Up to 128GB DDR5',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A5000',
            'form_factor': 'Tower'
        },
        'description': 'Mainstream workstation tower'
    },
    {
        'model_name': 'Z2 G8 SFF',
        'model_number': 'Z2 G8 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen or Xeon W',
            'memory': 'Up to 128GB DDR5',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A4000',
            'form_factor': 'Small Form Factor'
        },
        'description': 'Compact workstation SFF'
    },
    {
        'model_name': 'Z2 G5 Tower',
        'model_number': 'Z2 G5 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon W',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A5000',
            'form_factor': 'Tower'
        },
        'description': 'Mainstream workstation tower'
    },
    {
        'model_name': 'Z2 G5 SFF',
        'model_number': 'Z2 G5 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon W',
            'memory': 'Up to 128GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'NVIDIA Quadro/RTX A series',
            'form_factor': 'Small Form Factor'
        },
        'description': 'Compact workstation SFF'
    },
    {
        'model_name': 'Z2 G4 Tower',
        'model_number': 'Z2 G4 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 9th Gen or Xeon E',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Multiple M.2 NVMe + SATA',
            'graphics': 'NVIDIA Quadro RTX 5000',
            'form_factor': 'Tower'
        },
        'description': 'Mainstream workstation tower'
    },
    {
        'model_name': 'Z2 G4 SFF',
        'model_number': 'Z2 G4 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 9th Gen or Xeon E',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'NVIDIA Quadro P series',
            'form_factor': 'Small Form Factor'
        },
        'description': 'Compact workstation SFF'
    },
    {
        'model_name': 'Z1 G9 Tower',
        'model_number': 'Z1 G9 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen',
            'memory': 'Up to 128GB DDR5',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A2000',
            'form_factor': 'Tower'
        },
        'description': 'Entry workstation tower'
    },
    {
        'model_name': 'Z1 G8 Tower',
        'model_number': 'Z1 G8 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 12th Gen',
            'memory': 'Up to 128GB DDR5',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'NVIDIA RTX up to RTX A2000',
            'form_factor': 'Tower'
        },
        'description': 'Entry workstation tower'
    },
    {
        'model_name': 'Z1 G6',
        'model_number': 'Z1 G6',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 10th Gen',
            'memory': 'Up to 128GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'graphics': 'NVIDIA Quadro P series',
            'form_factor': 'Tower'
        },
        'description': 'Entry workstation tower'
    },
    {
        'model_name': 'Z240 Tower',
        'model_number': 'Z240',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 6th/7th Gen or Xeon E3',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 + SATA',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Tower'
        },
        'description': 'Entry workstation'
    },
    {
        'model_name': 'Z240 SFF',
        'model_number': 'Z240 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 6th/7th Gen or Xeon E3',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 + SATA',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Small Form Factor'
        },
        'description': 'Compact entry workstation'
    },
    {
        'model_name': 'Z440',
        'model_number': 'Z440',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Xeon E5-1600 v4',
            'memory': 'Up to 128GB DDR4',
            'storage': 'Multiple SATA + M.2',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Tower'
        },
        'description': 'Single-socket workstation'
    },
    {
        'model_name': 'Z640',
        'model_number': 'Z640',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 256GB DDR4',
            'storage': 'Multiple SATA + M.2',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Tower'
        },
        'description': 'Dual-socket workstation'
    },
    {
        'model_name': 'Z840',
        'model_number': 'Z840',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Dual Intel Xeon E5-2600 v4',
            'memory': 'Up to 1TB DDR4',
            'storage': 'Multiple SATA + M.2',
            'graphics': 'Up to 3x NVIDIA Quadro',
            'form_factor': 'Tower'
        },
        'description': 'High-end dual-socket workstation'
    },
    {
        'model_name': 'Z230 Tower',
        'model_number': 'Z230',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 4th Gen or Xeon E3 v3',
            'memory': 'Up to 32GB DDR3',
            'storage': 'Multiple SATA',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Tower'
        },
        'description': 'Entry workstation'
    },
    {
        'model_name': 'Z230 SFF',
        'model_number': 'Z230 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 4th Gen or Xeon E3 v3',
            'memory': 'Up to 32GB DDR3',
            'storage': 'SATA',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Small Form Factor'
        },
        'description': 'Compact entry workstation'
    },
    {
        'model_name': 'Z220 Tower',
        'model_number': 'Z220',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 3rd Gen or Xeon E3 v2',
            'memory': 'Up to 32GB DDR3',
            'storage': 'Multiple SATA',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Tower'
        },
        'description': 'Entry workstation'
    },
    {
        'model_name': 'Z220 SFF',
        'model_number': 'Z220 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 3rd Gen or Xeon E3 v2',
            'memory': 'Up to 32GB DDR3',
            'storage': 'SATA',
            'graphics': 'NVIDIA Quadro',
            'form_factor': 'Small Form Factor'
        },
        'description': 'Compact entry workstation'
    },

    # ============================================
    # HP ELITEDESK BUSINESS DESKTOPS
    # ============================================
    {
        'model_name': 'EliteDesk 800 G9 Tower',
        'model_number': '800 G9 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen or Xeon',
            'memory': 'Up to 128GB DDR5',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business tower desktop'
    },
    {
        'model_name': 'EliteDesk 800 G9 SFF',
        'model_number': '800 G9 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen',
            'memory': 'Up to 128GB DDR5',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business SFF desktop'
    },
    {
        'model_name': 'EliteDesk 800 G9 Mini',
        'model_number': '800 G9 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 13th Gen',
            'memory': 'Up to 64GB DDR5',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Ultra-compact premium desktop'
    },
    {
        'model_name': 'EliteDesk 800 G8 Tower',
        'model_number': '800 G8 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen or Xeon',
            'memory': 'Up to 128GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business tower desktop'
    },
    {
        'model_name': 'EliteDesk 800 G8 SFF',
        'model_number': '800 G8 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen',
            'memory': 'Up to 128GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business SFF desktop'
    },
    {
        'model_name': 'EliteDesk 800 G8 Mini',
        'model_number': '800 G8 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 11th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Ultra-compact premium desktop'
    },
    {
        'model_name': 'EliteDesk 800 G6 Tower',
        'model_number': '800 G6 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 10th Gen',
            'memory': 'Up to 128GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business tower desktop'
    },
    {
        'model_name': 'EliteDesk 800 G6 SFF',
        'model_number': '800 G6 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business SFF desktop'
    },
    {
        'model_name': 'EliteDesk 800 G6 Mini',
        'model_number': '800 G6 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Ultra-compact premium desktop'
    },
    {
        'model_name': 'EliteDesk 800 G5 Tower',
        'model_number': '800 G5 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 9th Gen',
            'memory': 'Up to 128GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business tower desktop'
    },
    {
        'model_name': 'EliteDesk 800 G5 SFF',
        'model_number': '800 G5 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 9th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business SFF desktop'
    },
    {
        'model_name': 'EliteDesk 800 G5 Mini',
        'model_number': '800 G5 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7/i9 9th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Ultra-compact premium desktop'
    },
    {
        'model_name': 'EliteDesk 800 G4 Tower',
        'model_number': '800 G4 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business tower desktop'
    },
    {
        'model_name': 'EliteDesk 800 G4 SFF',
        'model_number': '800 G4 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Premium business SFF desktop'
    },
    {
        'model_name': 'EliteDesk 800 G4 Mini',
        'model_number': '800 G4 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i5/i7 8th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Ultra-compact premium desktop'
    },
    {
        'model_name': 'EliteDesk 705 G5 SFF',
        'model_number': '705 G5 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 3rd Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated or discrete'
        },
        'description': 'AMD-based premium SFF desktop'
    },
    {
        'model_name': 'EliteDesk 705 G5 Mini',
        'model_number': '705 G5 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 3rd Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'AMD-based ultra-compact desktop'
    },
    {
        'model_name': 'EliteDesk 705 G4 Tower',
        'model_number': '705 G4 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 2nd Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'AMD-based business tower'
    },
    {
        'model_name': 'EliteDesk 705 G4 SFF',
        'model_number': '705 G4 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 2nd Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'AMD-based business SFF'
    },
    {
        'model_name': 'EliteDesk 705 G4 Mini',
        'model_number': '705 G4 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'AMD Ryzen 5/7 PRO 2nd Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'AMD-based ultra-compact desktop'
    },

    # ============================================
    # HP PRODESK BUSINESS DESKTOPS
    # ============================================
    {
        'model_name': 'ProDesk 600 G6 Tower',
        'model_number': '600 G6 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 10th Gen',
            'memory': 'Up to 128GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Mainstream business tower'
    },
    {
        'model_name': 'ProDesk 600 G6 SFF',
        'model_number': '600 G6 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Mainstream business SFF'
    },
    {
        'model_name': 'ProDesk 600 G6 Mini',
        'model_number': '600 G6 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Compact mainstream desktop'
    },
    {
        'model_name': 'ProDesk 600 G5 Tower',
        'model_number': '600 G5 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 9th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Mainstream business tower'
    },
    {
        'model_name': 'ProDesk 600 G5 SFF',
        'model_number': '600 G5 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 9th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Mainstream business SFF'
    },
    {
        'model_name': 'ProDesk 600 G5 Mini',
        'model_number': '600 G5 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 9th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Compact mainstream desktop'
    },
    {
        'model_name': 'ProDesk 600 G4 Tower',
        'model_number': '600 G4 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 8th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated or discrete'
        },
        'description': 'Mainstream business tower'
    },
    {
        'model_name': 'ProDesk 600 G4 SFF',
        'model_number': '600 G4 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 8th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Mainstream business SFF'
    },
    {
        'model_name': 'ProDesk 600 G4 Mini',
        'model_number': '600 G4 Mini',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 8th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Mini Desktop',
            'graphics': 'Integrated'
        },
        'description': 'Compact mainstream desktop'
    },
    {
        'model_name': 'ProDesk 400 G7 Tower',
        'model_number': '400 G7 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated'
        },
        'description': 'Essential business tower'
    },
    {
        'model_name': 'ProDesk 400 G7 SFF',
        'model_number': '400 G7 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 10th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Essential business SFF'
    },
    {
        'model_name': 'ProDesk 400 G6 Tower',
        'model_number': '400 G6 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 9th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated'
        },
        'description': 'Essential business tower'
    },
    {
        'model_name': 'ProDesk 400 G6 SFF',
        'model_number': '400 G6 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 9th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Essential business SFF'
    },
    {
        'model_name': 'ProDesk 400 G5 Tower',
        'model_number': '400 G5 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 8th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'M.2 NVMe + SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated'
        },
        'description': 'Essential business tower'
    },
    {
        'model_name': 'ProDesk 400 G5 SFF',
        'model_number': '400 G5 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 8th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'M.2 NVMe',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Essential business SFF'
    },
    {
        'model_name': 'ProDesk 400 G4 Tower',
        'model_number': '400 G4 Tower',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 7th Gen',
            'memory': 'Up to 64GB DDR4',
            'storage': 'SATA',
            'form_factor': 'Tower',
            'graphics': 'Integrated'
        },
        'description': 'Essential business tower'
    },
    {
        'model_name': 'ProDesk 400 G4 SFF',
        'model_number': '400 G4 SFF',
        'equipment_type': 'workstation',
        'is_rackmount': False,
        'specifications': {
            'processor': 'Intel Core i3/i5/i7 7th Gen',
            'memory': 'Up to 32GB DDR4',
            'storage': 'SATA',
            'form_factor': 'Small Form Factor',
            'graphics': 'Integrated'
        },
        'description': 'Essential business SFF'
    },
]
