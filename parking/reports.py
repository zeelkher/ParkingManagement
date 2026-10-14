import io
from datetime import datetime
from decimal import Decimal

import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from django.utils import timezone
from .models import PLATE_TYPES
from .analytics import compute_analytics

PLATE_LABELS = dict(PLATE_TYPES)

# Available factor columns that can be customized by the user
AVAILABLE_COLUMNS = {
    'id': {'title': 'Ticket ID', 'default': True, 'width': 12, 'align': 'center'},
    'vehicle_number': {'title': 'Vehicle Number', 'default': True, 'width': 18, 'align': 'center'},
    'vehicle_type': {'title': 'Vehicle Type', 'default': True, 'width': 16, 'align': 'left'},
    'plate_type': {'title': 'Plate Category', 'default': True, 'width': 22, 'align': 'left'},
    'state_code': {'title': 'State', 'default': False, 'width': 10, 'align': 'center'},
    'owner_name': {'title': 'Owner Name', 'default': True, 'width': 22, 'align': 'left'},
    'mobile': {'title': 'Mobile Number', 'default': True, 'width': 16, 'align': 'center'},
    'area': {'title': 'Parking Area', 'default': True, 'width': 20, 'align': 'left'},
    'floor': {'title': 'Floor', 'default': True, 'width': 16, 'align': 'left'},
    'slot': {'title': 'Slot Number', 'default': True, 'width': 14, 'align': 'center'},
    'entry_time': {'title': 'Entry Time', 'default': True, 'width': 22, 'align': 'center'},
    'exit_time': {'title': 'Exit Time', 'default': True, 'width': 22, 'align': 'center'},
    'duration_formatted': {'title': 'Duration', 'default': True, 'width': 16, 'align': 'center'},
    'duration_hours': {'title': 'Duration (Hrs)', 'default': False, 'width': 16, 'align': 'right'},
    'fee': {'title': 'Parking Fee (₹)', 'default': True, 'width': 18, 'align': 'right'},
    'status': {'title': 'Status', 'default': True, 'width': 14, 'align': 'center'},
}


def build_excel_report(queryset, filter_info=None, selected_columns=None, include_summary_sheet=True):
    """
    Generate an openpyxl Workbook with:
    1. Filtered records worksheet with custom selected factors/columns
    2. Optional Executive Analytics & KPI summary worksheet
    Returns a BytesIO stream.
    """
    filter_info = filter_info or {}
    if not selected_columns:
        selected_columns = [col_key for col_key, meta in AVAILABLE_COLUMNS.items() if meta['default']]

    wb = openpyxl.Workbook()

    # Sheet 1: Records
    ws_records = wb.active
    ws_records.title = "Parking Records"
    ws_records.views.sheetView[0].showGridLines = True

    # Styling definitions
    title_font = Font(name='Segoe UI', size=16, bold=True, color='FFFFFF')
    subtitle_font = Font(name='Segoe UI', size=10, italic=True, color='CBD5E1')
    meta_label_font = Font(name='Segoe UI', size=9, bold=True, color='475569')
    meta_val_font = Font(name='Segoe UI', size=9, bold=False, color='1E293B')

    header_font = Font(name='Segoe UI', size=11, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='1E3A8A', end_color='1E3A8A', fill_type='solid') # Navy Blue

    zebra_fill = PatternFill(start_color='F8FAFC', end_color='F8FAFC', fill_type='solid')
    white_fill = PatternFill(start_color='FFFFFF', end_color='FFFFFF', fill_type='solid')

    total_font = Font(name='Segoe UI', size=11, bold=True, color='1E293B')
    total_fill = PatternFill(start_color='E2E8F0', end_color='E2E8F0', fill_type='solid')

    thin_border_side = Side(border_style='thin', color='E2E8F0')
    cell_border = Border(left=thin_border_side, right=thin_border_side, top=thin_border_side, bottom=thin_border_side)
    thick_top_border = Border(top=Side(border_style='medium', color='1E3A8A'), bottom=Side(border_style='double', color='1E3A8A'))

    num_cols = len(selected_columns)
    max_col_letter = get_column_letter(max(num_cols, 4))

    # Banner Header (Rows 1-2)
    ws_records.merge_cells(f"A1:{max_col_letter}1")
    title_cell = ws_records['A1']
    title_cell.value = "PARK NEST — COMPREHENSIVE PARKING AUDIT REPORT"
    title_cell.font = title_font
    title_cell.alignment = Alignment(horizontal='center', vertical='center')
    title_cell.fill = PatternFill(start_color='0F172A', end_color='0F172A', fill_type='solid') # Dark Slate

    ws_records.merge_cells(f"A2:{max_col_letter}2")
    sub_cell = ws_records['A2']
    now_str = timezone.localtime(timezone.now()).strftime('%d %B %Y, %I:%M %p')
    sub_cell.value = f"Generated on {now_str} • Filter Period: {filter_info.get('range_label', 'All Time')}"
    sub_cell.font = subtitle_font
    sub_cell.alignment = Alignment(horizontal='center', vertical='center')
    sub_cell.fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')

    ws_records.row_dimensions[1].height = 34
    ws_records.row_dimensions[2].height = 20

    # Metadata rows (Rows 4-5)
    records_list = list(queryset.order_by('-entry_time'))
    total_count = len(records_list)
    total_revenue = sum((r.parking_fee or Decimal('0.00')) for r in records_list if r.status == 'Exited')

    ws_records['A4'] = "Filter Scope:"
    ws_records['A4'].font = meta_label_font
    ws_records['B4'] = filter_info.get('range_label', 'All Time')
    ws_records['B4'].font = meta_val_font

    ws_records['A5'] = "Vehicle Filter:"
    ws_records['A5'].font = meta_label_font
    ws_records['B5'] = filter_info.get('vehicle_type', 'All').title()
    ws_records['B5'].font = meta_val_font

    if num_cols >= 4:
        c_col = get_column_letter(num_cols - 1)
        d_col = get_column_letter(num_cols)
        ws_records[f'{c_col}4'] = "Total Records:"
        ws_records[f'{c_col}4'].font = meta_label_font
        ws_records[f'{d_col}4'] = total_count
        ws_records[f'{d_col}4'].font = meta_val_font

        ws_records[f'{c_col}5'] = "Total Revenue:"
        ws_records[f'{c_col}5'].font = meta_label_font
        ws_records[f'{d_col}5'] = f"₹ {total_revenue:,.2f}"
        ws_records[f'{d_col}5'].font = meta_val_font

    # Column Headers on Row 7
    header_row_idx = 7
    ws_records.row_dimensions[header_row_idx].height = 28

    for c_idx, col_key in enumerate(selected_columns, start=1):
        col_meta = AVAILABLE_COLUMNS.get(col_key, {'title': col_key.title(), 'align': 'left'})
        cell = ws_records.cell(row=header_row_idx, column=c_idx, value=col_meta['title'])
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    # Data Rows
    current_row = header_row_idx + 1
    fee_col_idx = None
    duration_hours_col_idx = None

    for r_idx, r in enumerate(records_list):
        is_zebra = (r_idx % 2 == 1)
        row_fill = zebra_fill if is_zebra else white_fill
        ws_records.row_dimensions[current_row].height = 20

        v = r.vehicle
        plate_type_label = PLATE_LABELS.get(v.plate_type, v.plate_type) if v else '—'
        entry_time_str = timezone.localtime(r.entry_time).strftime('%Y-%m-%d %H:%M') if r.entry_time else '—'
        exit_time_str = timezone.localtime(r.exit_time).strftime('%Y-%m-%d %H:%M') if r.exit_time else '—'

        for c_idx, col_key in enumerate(selected_columns, start=1):
            cell = ws_records.cell(row=current_row, column=c_idx)
            cell.fill = row_fill
            cell.border = cell_border

            align_h = AVAILABLE_COLUMNS.get(col_key, {}).get('align', 'left')
            cell.alignment = Alignment(horizontal=align_h, vertical='center')

            if col_key == 'id':
                cell.value = r.id
            elif col_key == 'vehicle_number':
                cell.value = v.vehicle_number if v else '—'
            elif col_key == 'vehicle_type':
                cell.value = v.vehicle_type if v else '—'
            elif col_key == 'plate_type':
                cell.value = plate_type_label
            elif col_key == 'state_code':
                cell.value = v.state_code if v else '—'
            elif col_key == 'owner_name':
                cell.value = v.owner_name if v else '—'
            elif col_key == 'mobile':
                cell.value = v.mobile if v else '—'
            elif col_key == 'area':
                cell.value = r.parking_area_name if r.parking_slot_id else '—'
            elif col_key == 'floor':
                cell.value = r.floor_name if r.parking_slot_id else '—'
            elif col_key == 'slot':
                cell.value = r.parking_number if r.parking_slot_id else f"Slot {r.slot_number}"
            elif col_key == 'entry_time':
                cell.value = entry_time_str
            elif col_key == 'exit_time':
                cell.value = exit_time_str
            elif col_key == 'duration_formatted':
                cell.value = r.formatted_duration if r.status == 'Exited' else 'Active'
            elif col_key == 'duration_hours':
                duration_hours_col_idx = c_idx
                cell.value = round(r.total_hours, 2) if r.total_hours else 0.0
                cell.number_format = '0.00'
            elif col_key == 'fee':
                fee_col_idx = c_idx
                cell.value = float(r.parking_fee) if r.parking_fee else 0.0
                cell.number_format = '"₹"#,##0.00'
            elif col_key == 'status':
                cell.value = r.status
                if r.status == 'Active':
                    cell.font = Font(name='Segoe UI', size=10, bold=True, color='2563EB')
                else:
                    cell.font = Font(name='Segoe UI', size=10, color='1E293B')

        current_row += 1

    # Total Row at the bottom
    if total_count > 0:
        total_row_idx = current_row
        ws_records.row_dimensions[total_row_idx].height = 24
        ws_records.cell(row=total_row_idx, column=1, value="TOTALS / SUMMARY").font = total_font

        for c_idx, col_key in enumerate(selected_columns, start=1):
            cell = ws_records.cell(row=total_row_idx, column=c_idx)
            cell.fill = total_fill
            cell.border = thick_top_border
            cell.font = total_font

            if col_key == 'fee':
                col_letter = get_column_letter(c_idx)
                cell.value = f"=SUM({col_letter}8:{col_letter}{total_row_idx - 1})"
                cell.number_format = '"₹"#,##0.00'
                cell.alignment = Alignment(horizontal='right', vertical='center')
            elif col_key == 'duration_hours':
                col_letter = get_column_letter(c_idx)
                cell.value = f"=AVERAGE({col_letter}8:{col_letter}{total_row_idx - 1})"
                cell.number_format = '0.00'
                cell.alignment = Alignment(horizontal='right', vertical='center')
            elif col_key == 'id':
                cell.value = f"{total_count} records"
                cell.alignment = Alignment(horizontal='center', vertical='center')

    # Auto-adjust column widths
    for c_idx, col_key in enumerate(selected_columns, start=1):
        col_letter = get_column_letter(c_idx)
        desired_width = AVAILABLE_COLUMNS.get(col_key, {}).get('width', 16)
        ws_records.column_dimensions[col_letter].width = max(desired_width, 12)

    # Sheet 2: Executive Summary & KPI Analytics (If requested)
    if include_summary_sheet:
        ws_summary = wb.create_sheet(title="Executive Summary")
        ws_summary.views.sheetView[0].showGridLines = True

        analytics = compute_analytics(queryset)
        kpis = analytics['kpis']

        # Header
        ws_summary.merge_cells("A1:G1")
        s_title = ws_summary['A1']
        s_title.value = "PARK NEST — EXECUTIVE PARKING PERFORMANCE AUDIT"
        s_title.font = title_font
        s_title.alignment = Alignment(horizontal='center', vertical='center')
        s_title.fill = PatternFill(start_color='0F172A', end_color='0F172A', fill_type='solid')
        ws_summary.row_dimensions[1].height = 34

        ws_summary.merge_cells("A2:G2")
        s_sub = ws_summary['A2']
        s_sub.value = f"Data Period: {filter_info.get('range_label', 'All Time')} • Audited on {now_str}"
        s_sub.font = subtitle_font
        s_sub.alignment = Alignment(horizontal='center', vertical='center')
        s_sub.fill = PatternFill(start_color='1E293B', end_color='1E293B', fill_type='solid')
        ws_summary.row_dimensions[2].height = 20

        # KPI Metric Cards Table (Rows 4-7)
        kpi_metrics = [
            ("Total Vehicles Parked", kpis['total_records'], "Total vehicle entry sessions"),
            ("Currently Active", kpis['active_records'], "Vehicles inside parking lot"),
            ("Completed Visits", kpis['exited_records'], "Successfully checked out"),
            ("Total Revenue Collected", f"₹ {kpis['total_revenue']:,.2f}", "Gross parking fee collected"),
            ("Average Ticket Revenue", f"₹ {kpis['avg_revenue']:,.2f}", "Revenue per checked out vehicle"),
            ("Average Parking Duration", kpis['avg_duration_formatted'], "Mean stay duration"),
            ("Peak Rush Hour", kpis['peak_hour_str'], f"{kpis['peak_hour_count']} check-ins during peak"),
            ("Busiest Day of Week", kpis['busiest_day_str'], f"{kpis['busiest_day_count']} entries on busiest day"),
            ("Electric Vehicle Share", f"{kpis['ev_percentage']}%", f"{kpis['ev_count']} EV green plates recorded"),
        ]

        ws_summary['A4'] = "EXECUTIVE KPI METRICS"
        ws_summary['A4'].font = Font(name='Segoe UI', size=12, bold=True, color='1E3A8A')

        card_header_fill = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
        ws_summary['A5'] = "Metric Name"
        ws_summary['B5'] = "Calculated Value"
        ws_summary['C5'] = "Operational Notes"
        for col_l in ['A', 'B', 'C']:
            c = ws_summary[f'{col_l}5']
            c.font = header_font
            c.fill = card_header_fill
            c.alignment = Alignment(horizontal='center', vertical='center')
        ws_summary.row_dimensions[5].height = 24

        curr_kpi_row = 6
        for m_name, m_val, m_note in kpi_metrics:
            is_z = (curr_kpi_row % 2 == 1)
            f_fill = zebra_fill if is_z else white_fill
            ws_summary.cell(row=curr_kpi_row, column=1, value=m_name).font = Font(name='Segoe UI', size=10, bold=True)
            ws_summary.cell(row=curr_kpi_row, column=2, value=m_val).font = Font(name='Segoe UI', size=11, bold=True, color='1E40AF')
            ws_summary.cell(row=curr_kpi_row, column=3, value=m_note).font = Font(name='Segoe UI', size=9, italic=True, color='64748B')
            for c_i in range(1, 4):
                ws_summary.cell(row=curr_kpi_row, column=c_i).fill = f_fill
                ws_summary.cell(row=curr_kpi_row, column=c_i).border = cell_border
            curr_kpi_row += 1

        # Breakdown Table 1: Revenue by Vehicle Type
        v_start_row = curr_kpi_row + 2
        ws_summary.cell(row=v_start_row, column=1, value="TRAFFIC & REVENUE BREAKDOWN BY VEHICLE TYPE").font = Font(name='Segoe UI', size=12, bold=True, color='1E3A8A')
        
        v_h_row = v_start_row + 1
        ws_summary.row_dimensions[v_h_row].height = 24
        v_headers = ["Vehicle Type", "Vehicles Count", "Traffic Share (%)", "Total Revenue (₹)", "Avg Duration"]
        for idx, h_text in enumerate(v_headers, start=1):
            c = ws_summary.cell(row=v_h_row, column=idx, value=h_text)
            c.font = header_font
            c.fill = header_fill
            c.alignment = Alignment(horizontal='center', vertical='center')

        curr_v_row = v_h_row + 1
        for vt in analytics['vehicle_types_data']:
            is_z = (curr_v_row % 2 == 1)
            f_fill = zebra_fill if is_z else white_fill
            ws_summary.cell(row=curr_v_row, column=1, value=vt['type'])
            ws_summary.cell(row=curr_v_row, column=2, value=vt['count'])
            ws_summary.cell(row=curr_v_row, column=3, value=f"{vt['percentage']}%")
            ws_summary.cell(row=curr_v_row, column=4, value=vt['revenue'])
            ws_summary.cell(row=curr_v_row, column=4).number_format = '"₹"#,##0.00'
            ws_summary.cell(row=curr_v_row, column=5, value=vt['avg_duration_str'])
            for c_i in range(1, 6):
                ws_summary.cell(row=curr_v_row, column=c_i).fill = f_fill
                ws_summary.cell(row=curr_v_row, column=c_i).border = cell_border
            curr_v_row += 1

        # Breakdown Table 2: Hourly Traffic Analysis
        h_start_row = curr_v_row + 2
        ws_summary.cell(row=h_start_row, column=1, value="PEAK HOUR DISTRIBUTION (HOURLY RUSH TRAFFIC)").font = Font(name='Segoe UI', size=12, bold=True, color='1E3A8A')
        
        h_h_row = h_start_row + 1
        ws_summary.row_dimensions[h_h_row].height = 24
        h_headers = ["Time Bucket", "Vehicle Entries", "Vehicle Exits", "Revenue Collected (₹)"]
        for idx, h_text in enumerate(h_headers, start=1):
            c = ws_summary.cell(row=h_h_row, column=idx, value=h_text)
            c.font = header_font
            c.fill = PatternFill(start_color='0D9488', end_color='0D9488', fill_type='solid') # Teal
            c.alignment = Alignment(horizontal='center', vertical='center')

        curr_h_row = h_h_row + 1
        h_data = analytics['hourly_chart_data']
        for i in range(24):
            is_z = (curr_h_row % 2 == 1)
            f_fill = zebra_fill if is_z else white_fill
            ws_summary.cell(row=curr_h_row, column=1, value=h_data['labels'][i])
            ws_summary.cell(row=curr_h_row, column=2, value=h_data['entries'][i])
            ws_summary.cell(row=curr_h_row, column=3, value=h_data['exits'][i])
            ws_summary.cell(row=curr_h_row, column=4, value=h_data['revenue'][i])
            ws_summary.cell(row=curr_h_row, column=4).number_format = '"₹"#,##0.00'
            for c_i in range(1, 5):
                ws_summary.cell(row=curr_h_row, column=c_i).fill = f_fill
                ws_summary.cell(row=curr_h_row, column=c_i).border = cell_border
            curr_h_row += 1

        # Auto width for summary sheet
        ws_summary.column_dimensions['A'].width = 28
        ws_summary.column_dimensions['B'].width = 24
        ws_summary.column_dimensions['C'].width = 30
        ws_summary.column_dimensions['D'].width = 24
        ws_summary.column_dimensions['E'].width = 20

    stream = io.BytesIO()
    wb.save(stream)
    stream.seek(0)
    return stream
