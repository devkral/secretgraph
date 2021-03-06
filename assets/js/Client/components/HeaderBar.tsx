import * as React from 'react'
import AppBar from '@material-ui/core/AppBar'
import Toolbar from '@material-ui/core/Toolbar'
import Typography from '@material-ui/core/Typography'
import MenuItem from '@material-ui/core/MenuItem'
import Menu from '@material-ui/core/Menu'
import IconButton from '@material-ui/core/IconButton'
import MenuIcon from '@material-ui/icons/Menu'
import AccountCircle from '@material-ui/icons/AccountCircle'
import Dialog from '@material-ui/core/Dialog'
import DialogActions from '@material-ui/core/DialogActions'
import DialogTitle from '@material-ui/core/DialogTitle'
import Button from '@material-ui/core/Button'
import DialogContent from '@material-ui/core/DialogContent'
import TextField from '@material-ui/core/TextField'
import FormControl from '@material-ui/core/FormControl'
import FormHelperText from '@material-ui/core/FormHelperText'
import Link from '@material-ui/core/Link'
import { useApolloClient } from '@apollo/client'
import { useStylesAndTheme } from '../theme'
import { exportConfig, exportConfigAsUrl } from '../utils/config'
import { elements } from '../editors'
import { serverConfigQuery } from '../queries/server'
import { MainContext, ConfigContext } from '../contexts'

import { encryptingPasswordLabel, encryptingPasswordHelp } from '../messages'

type Props = {
    openState: any
}
const menuRef: React.RefObject<any> = React.createRef()

function HeaderBar(props: Props) {
    const { openState } = props
    const { classes, theme } = useStylesAndTheme()
    const [menuOpen, setMenuOpen] = React.useState(false)
    const [exportOpen, setExportOpen] = React.useState(false)
    const [exportUrl, setExportUrl] = React.useState('')
    const [loadingExport, setLoadingExport] = React.useState(false)
    const { mainCtx, updateMainCtx } = React.useContext(MainContext)
    const { config, updateConfig } = React.useContext(ConfigContext)
    let title: string, documenttitle: string
    let client: any = null
    try {
        client = useApolloClient()
    } catch (exc) {}
    switch (mainCtx.action) {
        case 'add':
            let temp = elements.get(mainCtx.type as string)
            title = `Add: ${temp ? temp.label : 'unknown'}`
            documenttitle = `Secretgraph: ${title}`
            break
        case 'edit':
            title = `Edit: ${mainCtx.type}: ${
                mainCtx.title ? mainCtx.title : mainCtx.item
            }`
            documenttitle = `Secretgraph: ${title}`
            break
        case 'help':
            title = `Help: ${mainCtx.type}`
            documenttitle = `Secretgraph: ${title}`
            break
        case 'start':
            title = 'Secretgraph - Start'
            documenttitle = title
            break
        case 'import':
            title = 'Secretgraph - Import'
            documenttitle = title
            break
        default:
            if (mainCtx.title) {
                title = mainCtx.title as string
            } else {
                title = mainCtx.item as string
            }
            documenttitle = `Secretgraph: ${title}`
            break
    }

    const exportSettingsFile = async () => {
        if (!config) return
        setLoadingExport(true)
        const encryptingPw = (document.getElementById(
            'secretgraph-export-pw'
        ) as HTMLInputElement).value
        const sconfig: any = await client
            .query({
                query: serverConfigQuery,
            })
            .then((obj: any) => obj.data.secretgraph.config)
            .catch(() => setLoadingExport(false))
        if (!sconfig) {
            setLoadingExport(false)
            return
        }
        exportConfig(
            config,
            encryptingPw,
            sconfig.PBKDF2Iterations[0],
            'secretgraph_settings.json'
        )
        setExportOpen(false)
        setLoadingExport(false)
    }

    const exportSettingsUrl = async () => {
        await navigator.clipboard.writeText(exportUrl)
        setExportOpen(false)
    }

    const exportSettingsOpener = async () => {
        if (!config) return
        const encryptingPw = (document.getElementById(
            'secretgraph-export-pw'
        ) as HTMLInputElement | undefined)?.value
        let _exportUrl
        try {
            _exportUrl = await exportConfigAsUrl(client, config, encryptingPw)
        } catch (exc) {}

        setExportUrl(_exportUrl ? (_exportUrl as string) : '')
        setMenuOpen(false)
        setExportOpen(true)
        //const qr = qrcode(typeNumber, errorCorrectionLevel);
    }

    const openImporter = () => {
        setMenuOpen(false)
        updateMainCtx({
            action: 'import',
        })
    }

    let sidebarButton = null
    if (!openState.drawerOpen && config) {
        sidebarButton = (
            <IconButton
                edge="start"
                className={classes.sidebarButton}
                onClick={() => openState.setDrawerOpen(true)}
                color="inherit"
                aria-label="menu"
            >
                <MenuIcon />
            </IconButton>
        )
    }

    React.useLayoutEffect(() => {
        document.title = documenttitle
    }, [documenttitle])

    return (
        <AppBar position="sticky" className={classes.appBar}>
            <Dialog
                open={exportOpen}
                onClose={() => setExportOpen(false)}
                aria-labelledby="export-dialog-title"
            >
                <DialogTitle id="export-dialog-title">Export</DialogTitle>
                <DialogContent>
                    <FormControl>
                        <TextField
                            disabled={loadingExport}
                            fullWidth={true}
                            variant="outlined"
                            label={encryptingPasswordLabel}
                            id="secretgraph-export-pw"
                            inputProps={{
                                'aria-describedby':
                                    'secretgraph-export-pw-help',
                                autoComplete: 'new-password',
                            }}
                            type="password"
                        />
                        <FormHelperText id="secretgraph-export-pw-help">
                            {encryptingPasswordHelp}
                        </FormHelperText>
                    </FormControl>
                    <Link href={exportUrl} onClick={exportSettingsUrl}>
                        {exportUrl}
                    </Link>
                </DialogContent>
                <DialogActions>
                    <Button
                        onClick={() => setExportOpen(false)}
                        color="secondary"
                        disabled={loadingExport}
                    >
                        Close
                    </Button>
                    <Button
                        onClick={exportSettingsUrl}
                        color="primary"
                        disabled={loadingExport}
                    >
                        Export as url
                    </Button>
                    <Button
                        onClick={exportSettingsFile}
                        color="primary"
                        disabled={loadingExport}
                    >
                        Export as file
                    </Button>
                </DialogActions>
            </Dialog>
            <Toolbar className={classes.appBarToolBar}>
                {sidebarButton}
                <Typography variant="h6" className={classes.appBarTitle}>
                    {title}
                </Typography>
                <IconButton
                    edge="start"
                    className={classes.userButton}
                    color="inherit"
                    aria-label="user"
                    ref={menuRef}
                    onClick={() => setMenuOpen(true)}
                >
                    <AccountCircle />
                </IconButton>
                <Menu
                    anchorEl={menuRef.current}
                    anchorOrigin={{
                        vertical: 'top',
                        horizontal: 'right',
                    }}
                    transformOrigin={{
                        vertical: 'top',
                        horizontal: 'right',
                    }}
                    keepMounted
                    open={menuOpen}
                    onClose={() => setMenuOpen(false)}
                >
                    <MenuItem
                        className={!config ? classes.hidden : null}
                        onClick={() => setMenuOpen(false)}
                    >
                        Update Settings
                    </MenuItem>
                    <MenuItem
                        className={!config ? classes.hidden : null}
                        onClick={openImporter}
                    >
                        Load Settings
                    </MenuItem>
                    <MenuItem
                        className={!config ? classes.hidden : null}
                        onClick={exportSettingsOpener}
                    >
                        Export Settings
                    </MenuItem>
                    <MenuItem onClick={() => setMenuOpen(false)}>Help</MenuItem>
                </Menu>
            </Toolbar>
        </AppBar>
    )
}

export default HeaderBar
