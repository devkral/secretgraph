

import * as React from "react";
import Card from '@material-ui/core/Card';
import CardContent from '@material-ui/core/CardContent';
import { Theme } from "@material-ui/core/styles";
import CircularProgress from '@material-ui/core/CircularProgress';

import { useAsync } from "react-async"
import { saveAs } from 'file-saver';
import { useQuery, useApolloClient } from '@apollo/client';

import { ConfigInterface} from "../../interfaces"
import { MainContext, ConfigContext } from "../../contexts"
import { decryptContentId } from "../../utils/graphql"

import { contentQuery } from "../../queries/content"
import { useStylesAndTheme } from "../../theme";
import { newClusterLabel } from "../../messages";

import { ViewFrame, EditFrame } from "../ElementFrames";

type Props = {};

const ViewPostbox = (props: Props) => {
  const {classes, theme} = useStylesAndTheme();
  const { mainCtx } = React.useContext(MainContext);
  const client = useApolloClient();
  const { config } = React.useContext(ConfigContext);
  const { data, error } = useAsync({
    promise: decryptContentId(
      client,
      config as ConfigInterface,
      mainCtx.url as string,
      mainCtx.item as string
    ),
    suspense: true
  });
  if(error){
    throw error;
  }
  return (
    <ViewFrame
      shareurl=""
    >

    </ViewFrame>
  );
}

const AddPostbox = (props: Props) => {
  const {classes, theme} = useStylesAndTheme();

  return (
    <EditFrame
    >

    </EditFrame>
  );
}

const EditPostbox = (props: Props) => {
  const {classes, theme} = useStylesAndTheme();

  return (
    <EditFrame
      shareurl=""
    >

    </EditFrame>
  );
}

export default function PostboxComponent(props: Props) {
  const {mainCtx} = React.useContext(MainContext);
  if (mainCtx.action == "view" && mainCtx.item) {
    return (
      <ViewPostbox/>
    );
  } else if (mainCtx.action == "edit" && mainCtx.item) {
    return (<EditPostbox/>)
  } else if (mainCtx.action == "add") {
    return (<AddPostbox/>)
  }
  return null;
};