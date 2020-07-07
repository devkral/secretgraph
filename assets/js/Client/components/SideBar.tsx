
import * as React from "react";
import Drawer from '@material-ui/core/Drawer';
import List from "@material-ui/core/List";
import Typography from "@material-ui/core/Typography";
import TextField from '@material-ui/core/TextField';
import Hidden from '@material-ui/core/Hidden';
import Divider from "@material-ui/core/Divider";
import IconButton from "@material-ui/core/IconButton";
import Autocomplete from '@material-ui/lab/Autocomplete';
import ChevronLeftIcon from "@material-ui/icons/ChevronLeft";
import ChevronRightIcon from "@material-ui/icons/ChevronRight";
import ExpansionPanel from '@material-ui/core/ExpansionPanel';
import ExpansionPanelDetails from '@material-ui/core/ExpansionPanelDetails';
import ExpansionPanelSummary from '@material-ui/core/ExpansionPanelSummary';
import GroupWorkIcon from '@material-ui/icons/GroupWork';
import StarIcon from '@material-ui/icons/Star';
import ListItem from "@material-ui/core/ListItem";
import ListItemIcon from "@material-ui/core/ListItemIcon";
import ListItemText from "@material-ui/core/ListItemText";
import InboxIcon from "@material-ui/icons/MoveToInbox";
import MailOutlineIcon from '@material-ui/icons/MailOutline';
import DraftsIcon from '@material-ui/icons/Drafts';
import MailIcon from "@material-ui/icons/Mail";
import ExpandMoreIcon from '@material-ui/icons/ExpandMore';
import { Theme } from "@material-ui/core/styles";
import {createPaginationContainer, graphql} from 'react-relay';
import { themeComponent } from "../theme";
import { ConfigInterface, MainContextInterface } from "../interfaces";

type SideBarProps = {
  openState: any,
  classes: any,
  theme: Theme,
  mainContext: MainContextInterface,
  setMainContext: any,
  config: ConfigInterface
};

type SideBarHeaderProps = {
  classes: any,
  theme: Theme,
  closeButton: any
};


type SideBarControlProps = {
  classes: any,
  theme: Theme,
  config: ConfigInterface,
  mainContext: MainContextInterface,
  setMainContext: any
};

type SideBarItemsProps = {
  classes: any,
  theme: Theme,
  config: ConfigInterface,
  mainContext: MainContextInterface,
  setMainContext: any
};

const SideBarHeader = themeComponent((props: SideBarHeaderProps) => {
  const { classes, theme, closeButton } = props;
  const headerElements = (
    <Autocomplete
      className={classes.sideBarHeaderSelect}
      options={[]}
      renderInput={(params) => (
        <TextField
          {...params}
          label="Search content"
          variant="outlined"
          inputProps={{
            ...params.inputProps,
            autoComplete: 'new-password', // disable autocomplete and autofill
          }}
        />
      )}
    />
  );
  return (
    <div className={classes.sideBarHeader}>
      {theme.direction === "ltr" ? headerElements: null}
      {closeButton}
      {theme.direction === "rtl" ? headerElements: null}
    </div>
  )
})


const SideBarControl = themeComponent((props: SideBarControlProps) => {
  const { classes, theme, config, setMainContext, mainContext } = props;
  return (
    <ExpansionPanel>
      <ExpansionPanelSummary
        expandIcon={<ExpandMoreIcon />}
        aria-controls="Control-content"
        id="Control-header"
      >
        <Typography className={classes.heading}>Control</Typography>
      </ExpansionPanelSummary>
      <ExpansionPanelDetails>
        <List>
          <ListItem button key={"Inbox"} onClick={() => setMainContext({
            ...mainContext,
            action: "contents",
            filter: ["type=Message"],
            exclude: []
          })}>
            <ListItemIcon>
              <InboxIcon />
            </ListItemIcon>
          </ListItem>
          <ListItem button key={"Send"} onClick={() => setMainContext({
            ...mainContext,
            item: "Message",
            action: "edit",
          })}>
            <ListItemIcon>
              <InboxIcon />
            </ListItemIcon>
          </ListItem>
          <ListItem button key={"Drafts"} onClick={() => setMainContext({
            ...mainContext,
            action: "contents",
            filter: ["state=draft"],
            exclude: []
          })}>
            <ListItemIcon>
              <DraftsIcon />
            </ListItemIcon>
          </ListItem>
          <ListItem button key={"Cluster"} onClick={() => setMainContext({
            ...mainContext,
            action: "clusters",
            filter: [],
            exclude: []
          })}>
            <ListItemIcon>
              <GroupWorkIcon />
            </ListItemIcon>
          </ListItem>
        </List>
      </ExpansionPanelDetails>
    </ExpansionPanel>
  );
});

class ContentFeed extends React.Component {
  render() {
    return (
      <List>
        {this.props.user.feed.edges.map((text, index) => (
          <ListItem button key={text}>
            <ListItemIcon>
              {index % 2 === 0 ? <InboxIcon /> : <MailIcon />}
            </ListItemIcon>
            <ListItemText primary={text} />
          </ListItem>
        ))}

        <Divider />
        <ListItem button key={"loadmore"}
          disabled={(!this.props.relay.hasMore() || this.props.relay.isLoading())}
          onClick={() => {
            this._loadMore();
          }}
        >
          <ListItemText primary={"Load more..."} />
        </ListItem>
      </List>
    );
  }

  _loadMore() {
    if (!this.props.relay.hasMore() || this.props.relay.isLoading()) {
      return;
    }

    this.props.relay.loadMore(
      30,  // Fetch the next 10 feed items
      error => {
        console.log(error);
      },
    );
  }
}


const SideBarContents = themeComponent((props: SideBarItemsProps) => {
  const { classes, theme, config, mainContext, setMainContext } = props;
  const pager = createPaginationContainer(
    ,
    {
      user: graphql`
        fragment Feed_user on User
        @argumentDefinitions(
          count: {type: "Int", defaultValue: 10}
          cursor: {type: "ID"}
        ) {
          feed(
            first: $count
            after: $cursor
            orderby: $orderBy # Non-pagination variables
          ) @connection(key: "Feed_feed") {
            edges {
              node {
                id
                ...Story_story
              }
            }
          }
        }
      `,
    },
    {
      direction: 'forward',
      getConnectionFromProps(props) {
        return props.user && props.user.feed;
      },
      // This is also the default implementation of `getFragmentVariables` if it isn't provided.
      getFragmentVariables(prevVars, totalCount) {
        return {
          ...prevVars,
          count: totalCount,
        };
      },
      getVariables(props, {count, cursor}, fragmentVariables) {
        return {
          count,
          cursor,
          orderBy: fragmentVariables.orderBy,
          // userID isn't specified as an @argument for the fragment, but it should be a variable available for the fragment under the query root.
          userID: fragmentVariables.userID,
        };
      },
      query: graphql`
        # Pagination query to be fetched upon calling 'loadMore'.
        # Notice that we re-use our fragment, and the shape of this query matches our fragment spec.
        query FeedPaginationQuery(
          $count: Int!
          $cursor: ID
          $orderBy: [FriendsOrdering]!
          $userID: ID!
        ) {
          user: node(id: $userID) {
            ...Feed_user @arguments(count: $count, cursor: $cursor, orderBy: $orderBy)
          }
        }
      `
    }
  );
})

const _genClusters = function*(config: ConfigInterface) {
  for(const url in config.clusters) {
    for(const id in config.clusters[url]) {
      yield [url, id, config.clusters[url][id]]
    }
  }
}


class ClustersList {
  rows: Array<[string, string, any]>;
  iterator: any;

  constructor(config: ConfigInterface, initialRows=30) {
    this.rows = [];
    this.iterator = _genClusters(config)
    this.load(initialRows)
  }

  load(amountRows=30) {
    const rows: Array<[string, string, any]> = [];
    for(let counter=0;counter<amountRows; counter++){
      rows.push(this.iterator.next())
    }
    this.rows = this.rows.concat(rows);
    return this
  }
}

const SideBarClusters = themeComponent((props: SideBarItemsProps) => {
  const { classes, theme, config, mainContext, setMainContext } = props;
  const [rows, setRows] = React.useState(new ClustersList(config));

  return (
    <List>
      {rows.rows.map((value, index) => (
        <ListItem button key={`${value[0]}:${value[1]}`}
          onClick={() => {
            setMainContext({
              ...mainContext,
              cluster: [value[0], value[1]],
              item: "",
              action: "view",
              filter: [],
              exclude: []
            })
          }}
        >
          <ListItemIcon>
            <GroupWorkIcon />
          </ListItemIcon>
          <ListItemText primary={`${value[0]}:${value[1]}`} />
        </ListItem>
      ))}
      <Divider />
      <ListItem button key={"loadmore"}
        onClick={() => {
          setRows(rows.load());
        }}
      >
        <ListItemText primary={"Load more..."} />
      </ListItem>
    </List>
  );
})



function SideBar(props: SideBarProps) {
    const { classes, theme, openState, mainContext, setMainContext, config } = props;
    const closeButton = (
      <Hidden lgUp>
        <IconButton onClick={() => openState.setDrawerOpen(false)}>
          {theme.direction === "ltr" ? (
            <ChevronLeftIcon />
          ) : (
            <ChevronRightIcon />
          )}
        </IconButton>
      </Hidden>
    );
    let sideBarItems = (
      <SideBarClusters>
        setMainContext={setMainContext}
        mainContext={mainContext}
        config={config}
      </SideBarClusters>
    );
    return (
      <Drawer
        className={classes.drawer}
        variant="persistent"
        anchor={theme.direction === 'ltr' ? 'left' : 'right'}
        open={openState.drawerOpen}
        classes={{
          paper: classes.drawerPaper,
        }}
      >
        <SideBarHeader closeButton={closeButton} />
        <Divider />
        <div className={classes.sideBarBody}>
          <SideBarControl
            mainContext={mainContext}
            config={config}
          />
          {sideBarItems}
        </div>
      </Drawer>

    );
}

export default themeComponent(SideBar);
