"""
AI-powered floor plan generation using Claude.

This service uses Claude to intelligently design office floor plans based on:
- Building dimensions
- Number of employees
- Department structure
- Network requirements
- Security requirements
"""

import anthropic
from django.conf import settings
from .drawio_builder import DrawioFloorPlanBuilder
import json
import logging

logger = logging.getLogger('locations')


class AIFloorPlanGenerator:
    """Generate intelligent floor plans using Claude AI."""

    def __init__(self):
        self.client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    def generate_floor_plan(
        self,
        building_name: str,
        width_feet: float,
        length_feet: float,
        num_employees: int = 20,
        departments: list = None,
        include_network: bool = True,
        include_security: bool = True,
        additional_requirements: str = ""
    ) -> tuple[DrawioFloorPlanBuilder, dict]:
        """
        Generate a complete floor plan using AI.

        Args:
            building_name: Name of the building/office
            width_feet: Building width in feet
            length_feet: Building length in feet
            num_employees: Number of employees
            departments: List of department names (optional)
            include_network: Include network infrastructure
            include_security: Include security cameras/access control
            additional_requirements: Additional custom requirements

        Returns:
            (builder, metadata): DrawioFloorPlanBuilder instance and metadata dict
        """
        # Build the prompt for Claude
        prompt = self._build_design_prompt(
            building_name=building_name,
            width_feet=width_feet,
            length_feet=length_feet,
            num_employees=num_employees,
            departments=departments or [],
            include_network=include_network,
            include_security=include_security,
            additional_requirements=additional_requirements
        )

        logger.info(f"Generating floor plan for {building_name} ({width_feet}x{length_feet}ft)")

        # Get AI-generated design
        design = self._get_ai_design(prompt)

        # Build the floor plan from AI design
        builder = self._build_floor_plan_from_design(
            design=design,
            width_feet=width_feet,
            length_feet=length_feet
        )

        metadata = {
            'building_name': building_name,
            'dimensions': {'width': width_feet, 'length': length_feet},
            'num_employees': num_employees,
            'departments': departments,
            'ai_design': design,
            'generated_by': 'claude',
        }

        return builder, metadata

    def _build_design_prompt(
        self,
        building_name: str,
        width_feet: float,
        length_feet: float,
        num_employees: int,
        departments: list,
        include_network: bool,
        include_security: bool,
        additional_requirements: str
    ) -> str:
        """Build the prompt for Claude to design the floor plan."""

        dept_text = ""
        if departments:
            dept_text = f"Departments: {', '.join(departments)}"

        prompt = f"""You are an expert office space planner. Design an efficient office floor plan.

Building Details:
- Name: {building_name}
- Dimensions: {width_feet} feet wide × {length_feet} feet long
- Total square footage: {width_feet * length_feet:,.0f} sq ft
- Number of employees: {num_employees}
{dept_text}

Requirements:
- Efficient use of space
- Proper emergency exits and fire safety
- ADA compliance considerations
- Natural workflow patterns
{"- Network infrastructure (server room, APs, cabling)" if include_network else ""}
{"- Security systems (cameras, access control)" if include_security else ""}
{additional_requirements}

Please provide a detailed floor plan design in JSON format with the following structure:

{{
  "rooms": [
    {{
      "name": "Room Name",
      "type": "office|conference|server|kitchen|storage|restroom|reception|openspace",
      "x": 0,
      "y": 0,
      "width": 20,
      "height": 15,
      "notes": "Purpose and details"
    }}
  ],
  "doors": [
    {{
      "x": 10,
      "y": 0,
      "orientation": "horizontal|vertical",
      "connects": "Between Room A and Hallway"
    }}
  ],
  "network": [
    {{
      "type": "ap|switch|camera|access_control|server_rack",
      "name": "Device name",
      "x": 50,
      "y": 50,
      "coverage_radius": 50,
      "notes": "Purpose"
    }}
  ],
  "design_notes": "Overall design philosophy and key features"
}}

All coordinates are in feet from the top-left corner (0, 0).
Room layouts should maximize natural light, minimize hallway space, and create efficient workflows.
Include at least 2 emergency exits.
Server room should be climate controlled and centrally located for network runs.
Conference rooms near reception, private offices along perimeter, open space in center.
"""
        return prompt

    def _get_ai_design(self, prompt: str) -> dict:
        """Get floor plan design from Claude."""
        try:
            message = self.client.messages.create(
                model=settings.CLAUDE_MODEL,
                max_tokens=4096,
                messages=[
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )

            # Extract JSON from response
            response_text = message.content[0].text

            # Try to find JSON in the response
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1

            if json_start == -1 or json_end == 0:
                raise ValueError("No JSON found in AI response")

            json_text = response_text[json_start:json_end]
            design = json.loads(json_text)

            logger.info(f"AI generated design with {len(design.get('rooms', []))} rooms")
            return design

        except Exception as e:
            logger.error(f"AI design generation failed: {e}")
            # Fallback to basic design
            return self._get_fallback_design()

    def _get_fallback_design(self) -> dict:
        """Fallback design if AI fails."""
        return {
            "rooms": [
                {"name": "Reception", "type": "reception", "x": 5, "y": 5, "width": 20, "height": 15, "notes": "Main entrance"},
                {"name": "Conference Room", "type": "conference", "x": 30, "y": 5, "width": 25, "height": 20, "notes": "Main meeting space"},
                {"name": "Open Workspace", "type": "openspace", "x": 5, "y": 25, "width": 50, "height": 30, "notes": "Collaborative area"},
                {"name": "Server Room", "type": "server", "x": 60, "y": 5, "width": 15, "height": 15, "notes": "Network equipment"},
                {"name": "Kitchen", "type": "kitchen", "x": 60, "y": 25, "width": 15, "height": 15, "notes": "Break area"},
            ],
            "doors": [],
            "network": [],
            "design_notes": "Basic fallback layout"
        }

    def _build_floor_plan_from_design(
        self,
        design: dict,
        width_feet: float,
        length_feet: float
    ) -> DrawioFloorPlanBuilder:
        """Convert AI design JSON to Draw.io floor plan."""

        builder = DrawioFloorPlanBuilder(
            width_feet=width_feet,
            length_feet=length_feet,
            scale=10  # 10 pixels per foot
        )

        # Add building outline
        builder.add_building_outline()

        # Add all rooms
        for room in design.get('rooms', []):
            builder.add_room(
                name=room['name'],
                x_feet=room['x'],
                y_feet=room['y'],
                width_feet=room['width'],
                height_feet=room['height'],
                room_type=room.get('type', 'office'),
                add_label=True
            )

        # Add doors
        for door in design.get('doors', []):
            builder.add_door(
                x_feet=door['x'],
                y_feet=door['y'],
                orientation=door.get('orientation', 'horizontal')
            )

        # Add network infrastructure
        for device in design.get('network', []):
            device_type = device['type']

            if device_type == 'ap':
                builder.add_ap(
                    name=device['name'],
                    x_feet=device['x'],
                    y_feet=device['y'],
                    coverage_radius_feet=device.get('coverage_radius', 50)
                )
            elif device_type == 'camera':
                builder.add_camera(
                    name=device['name'],
                    x_feet=device['x'],
                    y_feet=device['y']
                )
            elif device_type == 'access_control':
                builder.add_access_control(
                    name=device['name'],
                    x_feet=device['x'],
                    y_feet=device['y']
                )

        # Add legend
        legend_items = [
            ("📡", "Wireless Access Point"),
            ("📹", "Security Camera"),
            ("🔐", "Access Control"),
            ("🚪", "Door/Exit"),
        ]
        builder.add_legend(legend_items)

        return builder


def generate_office_floor_plan(
    organization,
    location_name: str,
    address: str,
    width_feet: float = 100,
    length_feet: float = 80,
    **kwargs
) -> tuple[str, dict]:
    """
    High-level function to generate a floor plan for a location.

    Args:
        organization: Organization instance
        location_name: Name of the location
        address: Physical address
        width_feet: Building width
        length_feet: Building length
        **kwargs: Additional parameters for AIFloorPlanGenerator

    Returns:
        (xml_content, metadata): Draw.io XML string and metadata dict
    """
    generator = AIFloorPlanGenerator()

    builder, metadata = generator.generate_floor_plan(
        building_name=location_name,
        width_feet=width_feet,
        length_feet=length_feet,
        **kwargs
    )

    xml_content = builder.to_xml_string()

    metadata['organization_id'] = organization.id
    metadata['location_name'] = location_name
    metadata['address'] = address

    logger.info(f"Generated floor plan for {location_name}: {len(xml_content)} bytes")

    return xml_content, metadata
