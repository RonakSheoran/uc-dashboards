from command_centers import layout as command_layout, refresh_data

# Visual 7.1.1 | widget | gnhgks | Invoices disbursed under 5 minutes
# Visual 7.1.2 | widget | gnhgks | Eligible share
# Visual 7.1.3 | widget | gnhgks | Eligible P90 TAT
# Visual 7.1.4 | widget | gnhgks | Balance share
# Visual 7.1.5 | widget | gnhgks | Balance P90 TAT
# Visual 7.1.6 | table | gnhgks | Daily trend
# Visual 7.2.1 | table | gnhgks | Sequential eligibility waterfall counts
# Visual 7.2.2 | table | gnhgks | Sequential eligibility waterfall P90 TAT

# Deployment/startup refresh. Scheduled refreshes use the same public hook.
refresh_data()


def layout():
    return command_layout("invoice_command")
