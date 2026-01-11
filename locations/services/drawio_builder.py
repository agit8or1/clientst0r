"""
Draw.io XML Builder - Programmatically generate floor plan diagrams
"""
import xml.etree.ElementTree as ET
from typing import List, Dict, Tuple, Optional
import math


class DrawioFloorPlanBuilder:
    """
    Build draw.io XML for floor plans with rooms, equipment, and network infrastructure.
    """

    def __init__(self, width_feet: float, length_feet: float, scale: float = 10):
        """
        Initialize floor plan builder.

        Args:
            width_feet: Building width in feet
            length_feet: Building length in feet
            scale: Pixels per foot (default: 10 = 1 foot = 10 pixels)
        """
        self.width_feet = width_feet
        self.length_feet = length_feet
        self.scale = scale

        # Convert to pixels
        self.width_px = int(width_feet * scale)
        self.length_px = int(length_feet * scale)

        # XML structure
        self.root = ET.Element('mxfile')
        self.diagram = ET.SubElement(self.root, 'diagram', {
            'name': 'Floor Plan',
            'id': 'floor-plan-1'
        })
        self.model = ET.SubElement(self.diagram, 'mxGraphModel', {
            'dx': '1422',
            'dy': '794',
            'grid': '1',
            'gridSize': '10',
            'guides': '1',
            'tooltips': '1',
            'connect': '1',
            'arrows': '1',
            'fold': '1',
            'page': '1',
            'pageScale': '1',
            'pageWidth': str(self.width_px),
            'pageHeight': str(self.length_px),
            'math': '0',
            'shadow': '0'
        })

        # Root cell structure
        self.root_cell = ET.SubElement(self.model, 'root')
        ET.SubElement(self.root_cell, 'mxCell', {'id': '0'})
        ET.SubElement(self.root_cell, 'mxCell', {'id': '1', 'parent': '0'})

        # ID counter for unique cell IDs
        self.cell_id_counter = 2

        # Color schemes
        self.colors = {
            'wall': '#000000',
            'door': '#8B4513',
            'window': '#87CEEB',
            'reception': '#dae8fc',
            'office': '#fff2cc',
            'conference': '#d5e8d4',
            'server_room': '#f8cecc',
            'storage': '#f5f5f5',
            'restroom': '#e1d5e7',
            'ap': '#fff2cc',
            'camera': '#f8cecc',
            'access_control': '#ffe6cc',
            'network_line': '#0066CC',
        }

    def get_next_id(self) -> str:
        """Get next unique cell ID."""
        cell_id = f"cell-{self.cell_id_counter}"
        self.cell_id_counter += 1
        return cell_id

    def feet_to_px(self, feet: float) -> int:
        """Convert feet to pixels."""
        return int(feet * self.scale)

    def add_building_outline(self, wall_thickness: int = 3):
        """Add building perimeter outline."""
        cell_id = self.get_next_id()
        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': f'{self.width_feet}\' × {self.length_feet}\'',
            'style': f'rounded=0;whiteSpace=wrap;html=1;fillColor=none;strokeColor={self.colors["wall"]};strokeWidth={wall_thickness};fontSize=14;fontStyle=1;align=left;verticalAlign=top;',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': '0',
            'y': '0',
            'width': str(self.width_px),
            'height': str(self.length_px),
            'as': 'geometry'
        })

    def add_room(self, name: str, x_feet: float, y_feet: float,
                 width_feet: float, height_feet: float, room_type: str = 'office',
                 add_label: bool = True) -> str:
        """
        Add a room to the floor plan.

        Args:
            name: Room name/label
            x_feet, y_feet: Position in feet
            width_feet, height_feet: Dimensions in feet
            room_type: Type of room (affects color)
            add_label: Whether to add room name label

        Returns:
            Cell ID of the created room
        """
        cell_id = self.get_next_id()

        # Get color for room type
        fill_color = self.colors.get(room_type, self.colors['office'])

        # Calculate pixel positions
        x = self.feet_to_px(x_feet)
        y = self.feet_to_px(y_feet)
        width = self.feet_to_px(width_feet)
        height = self.feet_to_px(height_feet)

        # Create room cell
        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': name if add_label else '',
            'style': f'rounded=0;whiteSpace=wrap;html=1;fillColor={fill_color};strokeColor=#000000;strokeWidth=2;fontSize=12;fontStyle=1;',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x),
            'y': str(y),
            'width': str(width),
            'height': str(height),
            'as': 'geometry'
        })

        return cell_id

    def add_door(self, x_feet: float, y_feet: float, orientation: str = 'horizontal',
                 width_feet: float = 3) -> str:
        """
        Add a door.

        Args:
            x_feet, y_feet: Position in feet
            orientation: 'horizontal' or 'vertical'
            width_feet: Door width in feet (default 3')

        Returns:
            Cell ID of the door
        """
        cell_id = self.get_next_id()

        x = self.feet_to_px(x_feet)
        y = self.feet_to_px(y_feet)
        width = self.feet_to_px(width_feet)
        height = self.feet_to_px(0.5)  # Thin line for door

        if orientation == 'vertical':
            width, height = height, width

        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': '',
            'style': f'rounded=0;whiteSpace=wrap;html=1;fillColor={self.colors["door"]};strokeColor={self.colors["door"]};',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x),
            'y': str(y),
            'width': str(width),
            'height': str(height),
            'as': 'geometry'
        })

        return cell_id

    def add_ap(self, name: str, x_feet: float, y_feet: float,
               coverage_radius_feet: float = 50) -> str:
        """
        Add wireless access point.

        Args:
            name: AP identifier (e.g., 'AP-01')
            x_feet, y_feet: Position in feet
            coverage_radius_feet: WiFi coverage radius in feet

        Returns:
            Cell ID of the AP
        """
        cell_id = self.get_next_id()

        x = self.feet_to_px(x_feet)
        y = self.feet_to_px(y_feet)
        size = 40  # Fixed size for AP icon

        # Add coverage circle (semi-transparent)
        if coverage_radius_feet > 0:
            coverage_id = self.get_next_id()
            radius_px = self.feet_to_px(coverage_radius_feet)
            coverage_cell = ET.SubElement(self.root_cell, 'mxCell', {
                'id': coverage_id,
                'value': '',
                'style': 'ellipse;whiteSpace=wrap;html=1;fillColor=#fff2cc;strokeColor=#d6b656;opacity=30;',
                'vertex': '1',
                'parent': '1'
            })
            ET.SubElement(coverage_cell, 'mxGeometry', {
                'x': str(x - radius_px),
                'y': str(y - radius_px),
                'width': str(radius_px * 2),
                'height': str(radius_px * 2),
                'as': 'geometry'
            })

        # Add AP icon
        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': f'📡 {name}',
            'style': f'ellipse;whiteSpace=wrap;html=1;fillColor={self.colors["ap"]};strokeColor=#d6b656;fontSize=10;fontStyle=1;',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x - size // 2),
            'y': str(y - size // 2),
            'width': str(size),
            'height': str(size),
            'as': 'geometry'
        })

        return cell_id

    def add_camera(self, name: str, x_feet: float, y_feet: float) -> str:
        """Add security camera."""
        cell_id = self.get_next_id()

        x = self.feet_to_px(x_feet)
        y = self.feet_to_px(y_feet)
        size = 30

        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': f'📹 {name}',
            'style': f'ellipse;whiteSpace=wrap;html=1;fillColor={self.colors["camera"]};strokeColor=#b85450;fontSize=9;',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x - size // 2),
            'y': str(y - size // 2),
            'width': str(size),
            'height': str(size),
            'as': 'geometry'
        })

        return cell_id

    def add_access_control(self, name: str, x_feet: float, y_feet: float,
                          reader_type: str = 'card') -> str:
        """
        Add access control reader.

        Args:
            name: Reader identifier
            x_feet, y_feet: Position
            reader_type: 'card', 'biometric', 'keypad'
        """
        cell_id = self.get_next_id()

        x = self.feet_to_px(x_feet)
        y = self.feet_to_px(y_feet)
        width = 40
        height = 60

        # Icon based on type
        icon = {
            'card': '🔐',
            'biometric': '👁️',
            'keypad': '🔢'
        }.get(reader_type, '🔐')

        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': f'{icon}\\n{name}',
            'style': f'rounded=1;whiteSpace=wrap;html=1;fillColor={self.colors["access_control"]};strokeColor=#d79b00;fontSize=9;',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x - width // 2),
            'y': str(y - height // 2),
            'width': str(width),
            'height': str(height),
            'as': 'geometry'
        })

        return cell_id

    def add_network_line(self, x1_feet: float, y1_feet: float,
                        x2_feet: float, y2_feet: float, dashed: bool = True) -> str:
        """
        Add network backbone line connecting equipment.

        Args:
            x1_feet, y1_feet: Start point in feet
            x2_feet, y2_feet: End point in feet
            dashed: Use dashed line style
        """
        cell_id = self.get_next_id()

        x1 = self.feet_to_px(x1_feet)
        y1 = self.feet_to_px(y1_feet)
        x2 = self.feet_to_px(x2_feet)
        y2 = self.feet_to_px(y2_feet)

        style = f'endArrow=none;html=1;strokeWidth=2;strokeColor={self.colors["network_line"]};'
        if dashed:
            style += 'dashed=1;'

        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': '',
            'style': style,
            'edge': '1',
            'parent': '1'
        })
        geometry = ET.SubElement(cell, 'mxGeometry', {
            'width': '50',
            'height': '50',
            'relative': '1',
            'as': 'geometry'
        })
        ET.SubElement(geometry, 'mxPoint', {'x': str(x1), 'y': str(y1), 'as': 'sourcePoint'})
        ET.SubElement(geometry, 'mxPoint', {'x': str(x2), 'y': str(y2), 'as': 'targetPoint'})

        return cell_id

    def add_legend(self, x_feet: float = 5, y_feet: float = 5):
        """Add legend explaining symbols."""
        x = self.feet_to_px(x_feet)
        y = self.feet_to_px(y_feet)

        # Legend background
        cell_id = self.get_next_id()
        cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': cell_id,
            'value': '',
            'style': 'rounded=1;whiteSpace=wrap;html=1;fillColor=#f5f5f5;strokeColor=#666666;',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(cell, 'mxGeometry', {
            'x': str(x),
            'y': str(y),
            'width': '200',
            'height': '150',
            'as': 'geometry'
        })

        # Legend title
        title_id = self.get_next_id()
        title_cell = ET.SubElement(self.root_cell, 'mxCell', {
            'id': title_id,
            'value': '<b>Legend</b>',
            'style': 'text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontStyle=1;fontSize=14;',
            'vertex': '1',
            'parent': '1'
        })
        ET.SubElement(title_cell, 'mxGeometry', {
            'x': str(x + 10),
            'y': str(y + 10),
            'width': '180',
            'height': '20',
            'as': 'geometry'
        })

        # Legend items
        legend_items = [
            ('📡 Wireless AP', y + 40),
            ('🔐 Access Control', y + 60),
            ('📹 Security Camera', y + 80),
            ('--- Network Line', y + 100),
        ]

        for item_text, item_y in legend_items:
            item_id = self.get_next_id()
            item_cell = ET.SubElement(self.root_cell, 'mxCell', {
                'id': item_id,
                'value': item_text,
                'style': 'text;html=1;strokeColor=none;fillColor=none;align=left;verticalAlign=middle;whiteSpace=wrap;rounded=0;fontSize=10;',
                'vertex': '1',
                'parent': '1'
            })
            ET.SubElement(item_cell, 'mxGeometry', {
                'x': str(x + 20),
                'y': str(item_y),
                'width': '160',
                'height': '15',
                'as': 'geometry'
            })

    def to_xml_string(self) -> str:
        """Convert to XML string suitable for draw.io."""
        # Convert ElementTree to string
        xml_str = ET.tostring(self.root, encoding='unicode', method='xml')

        # Pretty print (optional - draw.io can handle minified XML)
        return xml_str

    def save_to_file(self, filename: str):
        """Save to file."""
        tree = ET.ElementTree(self.root)
        ET.indent(tree, space='  ')  # Pretty print
        tree.write(filename, encoding='utf-8', xml_declaration=True)


# Example usage and templates
def create_office_floor_plan(width_feet: float, length_feet: float,
                            num_offices: int = 4,
                            include_network: bool = True) -> str:
    """
    Create a basic office floor plan.

    Args:
        width_feet: Building width
        length_feet: Building length
        num_offices: Number of individual offices
        include_network: Include network infrastructure

    Returns:
        Draw.io XML string
    """
    builder = DrawioFloorPlanBuilder(width_feet, length_feet)

    # Add building outline
    builder.add_building_outline()

    # Reception area (front left)
    builder.add_room('Reception', 5, 5, 20, 15, 'reception')
    builder.add_door(15, 5, 'horizontal')

    # Hallway
    hallway_width = 6
    hallway_x = 30

    # Offices along hallway
    office_width = 12
    office_height = 10
    for i in range(num_offices):
        y = 5 + (i * (office_height + 2))
        builder.add_room(f'Office {i+1}', hallway_x + hallway_width + 2,
                        y, office_width, office_height, 'office')
        builder.add_door(hallway_x + hallway_width + 2, y + office_height // 2, 'vertical')

    # Conference room
    builder.add_room('Conference Room', hallway_x + hallway_width + 20, 5, 20, 15, 'conference')
    builder.add_door(hallway_x + hallway_width + 25, 5, 'horizontal')

    if include_network:
        # Add wireless APs
        builder.add_ap('AP-01', 15, length_feet / 4, coverage_radius_feet=40)
        builder.add_ap('AP-02', width_feet - 15, length_feet / 2, coverage_radius_feet=40)

        # Add access control at entrance
        builder.add_access_control('AC-01', 5, 12, 'card')

        # Add legend
        builder.add_legend(5, length_feet - 20)

    return builder.to_xml_string()
